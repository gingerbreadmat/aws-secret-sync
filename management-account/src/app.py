
import json
import boto3
import os

# Initialize AWS clients
secretsmanager = boto3.client("secretsmanager")
sts = boto3.client("sts")
tagging = boto3.client("resourcegroupstaggingapi")

# --- Constants ---
CONFIG_SECRET_ID = "secret-sync/config"
ROLE_TO_ASSUME = "SecretSyncRole"

# Tag Keys
TAG_SYNC_GROUP = "SecretSync-SyncDestinationGroup"
TAG_SYNC_ACCOUNT = "SecretSync-SyncAccount"
TAG_NO_SYNC_GROUP = "SecretSync-NoSyncDestinationGroup"
TAG_NO_SYNC_ACCOUNT = "SecretSync-NoSyncAccount"

SYNC_TAG_KEYS = [TAG_SYNC_GROUP, TAG_SYNC_ACCOUNT, TAG_NO_SYNC_GROUP, TAG_NO_SYNC_ACCOUNT]

def get_config(required=True):
    """Retrieves and parses the configuration from Secrets Manager."""
    try:
        response = secretsmanager.get_secret_value(SecretId=CONFIG_SECRET_ID)
        config = json.loads(response["SecretString"])
        print("Successfully loaded configuration.")
        return config
    except secretsmanager.exceptions.ResourceNotFoundException:
        if required:
            print(f"FATAL: Configuration secret {CONFIG_SECRET_ID} not found. This is required when using group-based tags.")
            raise
        else:
            print(f"Configuration secret {CONFIG_SECRET_ID} not found. Using individual account tags only.")
            return None
    except json.JSONDecodeError as e:
        print(f"FATAL: Could not parse configuration secret {CONFIG_SECRET_ID} as JSON. Error: {e}")
        raise
    except Exception as e:
        print(f"FATAL: Could not retrieve configuration secret {CONFIG_SECRET_ID}. Error: {e}")
        raise

def get_secrets_to_process():
    """Finds all secrets that have at least one of our sync tags."""
    print("Searching for all secrets to find resources to process...")
    paginator = tagging.get_paginator("get_resources")
    pages = paginator.paginate(ResourceTypeFilters=["secretsmanager:secret"])
    
    secrets_to_process = []
    for page in pages:
        for resource in page.get("ResourceTagMappingList", []):
            if any(tag['Key'] in SYNC_TAG_KEYS for tag in resource.get("Tags", [])):
                secrets_to_process.append(resource)
            
    print(f"Found {len(secrets_to_process)} secrets with sync-related tags.")
    return secrets_to_process

def resolve_sync_targets(tags, config):
    """
    Calculates the final list of (account_id, region) targets.
    """
    sync_targets = {}  # Using a dict to ensure one entry per account, mapping account_id -> region
    exclude_set = set()
    account_groups = config.get("AccountGroups", {}) if config else {}

    # Check for group-based tags when config is missing
    group_tags = [tag for tag in tags if tag.get("Key") in [TAG_SYNC_GROUP, TAG_NO_SYNC_GROUP]]
    if group_tags and not config:
        raise ValueError(f"Configuration secret {CONFIG_SECRET_ID} is required when using group-based tags: {[tag.get('Key') for tag in group_tags]}")

    # Inclusion Pass
    for tag in tags:
        key, value = tag.get("Key"), tag.get("Value")
        if key == TAG_SYNC_GROUP:
            group_info = account_groups.get(value, {})
            # Handle both old format (list) and new format (dict)
            accounts = group_info if isinstance(group_info, list) else group_info.get("Accounts", [])
            region = group_info.get("Region") if isinstance(group_info, dict) else None
            for account in accounts:
                sync_targets[account] = region
        elif key == TAG_SYNC_ACCOUNT:
            sync_targets[value] = None # Individual accounts sync to the Lambda's region

    # Exclusion Pass
    for tag in tags:
        key, value = tag.get("Key"), tag.get("Value")
        if key == TAG_NO_SYNC_GROUP:
            group_info = account_groups.get(value, {})
            accounts = group_info if isinstance(group_info, list) else group_info.get("Accounts", [])
            exclude_set.update(accounts)
        elif key == TAG_NO_SYNC_ACCOUNT:
            exclude_set.add(value)

    # Final Calculation
    final_targets = {acc: region for acc, region in sync_targets.items() if acc not in exclude_set}
    return list(final_targets.items())

def sync_to_single_account(account_id, region, secret_name, secret_value):
    """Assumes a role in a target account and creates/updates the secret in the specified region."""
    region_str = region if region else "the default region"
    print(f"  -> Syncing to account {account_id} in {region_str} as secret '{secret_name}'...")
    try:
        assumed_role = sts.assume_role(
            RoleArn=f"arn:aws:iam::{account_id}:role/{ROLE_TO_ASSUME}",
            RoleSessionName="SecretSyncSession"
        )
        credentials = assumed_role["Credentials"]
        
        target_sm_client = boto3.client(
            "secretsmanager",
            region_name=region,
            aws_access_key_id=credentials["AccessKeyId"],
            aws_secret_access_key=credentials["SecretAccessKey"],
            aws_session_token=credentials["SessionToken"],
        )

        try:
            target_sm_client.describe_secret(SecretId=secret_name)
            print(f"     Secret '{secret_name}' exists. Updating value.")
            target_sm_client.put_secret_value(SecretId=secret_name, SecretString=secret_value)
            print(f"     Successfully updated secret '{secret_name}' in account {account_id}.")
        except target_sm_client.exceptions.ResourceNotFoundException:
            print(f"     Secret '{secret_name}' not found. Creating it.")
            target_sm_client.create_secret(Name=secret_name, SecretString=secret_value)
            print(f"     Successfully created secret '{secret_name}' in account {account_id}.")

    except Exception as e:
        print(f"     ERROR: Failed to sync to account {account_id} in region {region}. Error: {e}")

def lambda_handler(event, context):
    """Main function for the Lambda."""
    secrets_to_process = get_secrets_to_process()
    
    # Check if any secrets use group-based tags
    group_based_tags = [TAG_SYNC_GROUP, TAG_NO_SYNC_GROUP]
    config_required = False
    
    for resource in secrets_to_process:
        tags = resource.get("Tags", [])
        if any(tag.get("Key") in group_based_tags for tag in tags):
            config_required = True
            break
    
    # Only load config if needed
    config = get_config(required=config_required)

    for resource in secrets_to_process:
        secret_arn = resource["ResourceARN"]
        tags = resource.get("Tags", [])
        
        try:
            final_targets = resolve_sync_targets(tags, config)

            if not final_targets:
                print(f"Skipping secret {secret_arn}: no target accounts after calculating rules.")
                continue

            print(f"Processing secret {secret_arn} for {len(final_targets)} target(s).")

            describe_response = secretsmanager.describe_secret(SecretId=secret_arn)
            secret_name = describe_response["Name"]
            secret_response = secretsmanager.get_secret_value(SecretId=secret_arn)
            secret_value = secret_response["SecretString"]
            
            for account_id, region in final_targets:
                sync_to_single_account(account_id, region, secret_name, secret_value)

        except Exception as e:
            print(f"ERROR: Could not process secret {secret_arn}. Error: {e}")

    return {
        "statusCode": 200,
        "body": json.dumps("Secret sync process completed.")
    }
