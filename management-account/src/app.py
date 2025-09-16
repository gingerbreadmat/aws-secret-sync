
import json
import boto3
import os

# Initialize AWS clients
secretsmanager = boto3.client("secretsmanager")
sts = boto3.client("sts")
tagging = boto3.client("resourcegroupstaggingapi")

# Get management account ID
MANAGEMENT_ACCOUNT_ID = sts.get_caller_identity()["Account"]

# --- Constants ---
CONFIG_SECRET_ID = "secret-sync/config"
ROLE_TO_ASSUME = "SecretSyncRole"

# Tag Keys
TAG_SYNC_GROUP = "SecretSync-SyncDestinationGroup"
TAG_SYNC_ACCOUNT = "SecretSync-SyncAccount"
TAG_NO_SYNC_GROUP = "SecretSync-NoSyncDestinationGroup"
TAG_NO_SYNC_ACCOUNT = "SecretSync-NoSyncAccount"
TAG_DELETE_GROUP = "SecretSync-DeleteDestinationGroup"
TAG_DELETE_ACCOUNT = "SecretSync-DeleteAccount"

SYNC_TAG_KEYS = [TAG_SYNC_GROUP, TAG_SYNC_ACCOUNT, TAG_NO_SYNC_GROUP, TAG_NO_SYNC_ACCOUNT, TAG_DELETE_GROUP, TAG_DELETE_ACCOUNT]

def get_config():
    """Retrieves and parses the configuration from Secrets Manager."""
    try:
        response = secretsmanager.get_secret_value(SecretId=CONFIG_SECRET_ID)
        config = json.loads(response["SecretString"])
        print("Successfully loaded configuration.")
        return config
    except Exception as e:
        print(f"FATAL: Could not retrieve or parse configuration secret {CONFIG_SECRET_ID}. Error: {e}")
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
    account_groups = config.get("AccountGroups", {})

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

def resolve_delete_targets(tags, config):
    """
    Calculates the final list of (account_id, region) targets for deletion.
    """
    delete_targets = {}  # Using a dict to ensure one entry per account, mapping account_id -> region
    account_groups = config.get("AccountGroups", {})

    # Process delete tags
    for tag in tags:
        key, value = tag.get("Key"), tag.get("Value")
        if key == TAG_DELETE_GROUP:
            group_info = account_groups.get(value, {})
            # Handle both old format (list) and new format (dict)
            accounts = group_info if isinstance(group_info, list) else group_info.get("Accounts", [])
            region = group_info.get("Region") if isinstance(group_info, dict) else None
            for account in accounts:
                delete_targets[account] = region
        elif key == TAG_DELETE_ACCOUNT:
            delete_targets[value] = None # Individual accounts delete from the Lambda's region

    return list(delete_targets.items())

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
            secret_info = target_sm_client.describe_secret(SecretId=secret_name)
            print(f"     Secret '{secret_name}' exists. Updating value.")
            target_sm_client.put_secret_value(SecretId=secret_name, SecretString=secret_value)
            
            # Add management tag to existing secret
            target_sm_client.tag_resource(
                SecretId=secret_info["ARN"],
                Tags=[{"Key": "SyncedFrom", "Value": MANAGEMENT_ACCOUNT_ID}]
            )
            print(f"     Successfully updated secret '{secret_name}' in account {account_id}.")
        except target_sm_client.exceptions.ResourceNotFoundException:
            print(f"     Secret '{secret_name}' not found. Creating it.")
            response = target_sm_client.create_secret(
                Name=secret_name, 
                SecretString=secret_value,
                Tags=[{"Key": "SyncedFrom", "Value": MANAGEMENT_ACCOUNT_ID}]
            )
            print(f"     Successfully created secret '{secret_name}' in account {account_id}.")

    except Exception as e:
        print(f"     ERROR: Failed to sync to account {account_id} in region {region}. Error: {e}")

def delete_from_single_account(account_id, region, secret_name):
    """Assumes a role in a target account and deletes the secret if it was managed by us."""
    region_str = region if region else "the default region"
    print(f"  -> Deleting from account {account_id} in {region_str} secret '{secret_name}'...")
    try:
        assumed_role = sts.assume_role(
            RoleArn=f"arn:aws:iam::{account_id}:role/{ROLE_TO_ASSUME}",
            RoleSessionName="SecretSyncDeleteSession"
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
            # Check if secret exists and is managed by us
            secret_info = target_sm_client.describe_secret(SecretId=secret_name)
            
            # Verify this secret was synced by our management account
            tags = secret_info.get("Tags", [])
            synced_from_tag = next((tag for tag in tags if tag["Key"] == "SyncedFrom"), None)
            
            if not synced_from_tag:
                print(f"     WARNING: Secret '{secret_name}' has no SyncedFrom tag. Skipping deletion for safety.")
                return
            
            if synced_from_tag["Value"] != MANAGEMENT_ACCOUNT_ID:
                print(f"     WARNING: Secret '{secret_name}' was synced from account {synced_from_tag['Value']}, not our management account {MANAGEMENT_ACCOUNT_ID}. Skipping deletion.")
                return
            
            # Safe to delete - this secret was managed by us
            target_sm_client.delete_secret(SecretId=secret_name, ForceDeleteWithoutRecovery=True)
            print(f"     Successfully deleted secret '{secret_name}' from account {account_id}.")
            
        except target_sm_client.exceptions.ResourceNotFoundException:
            print(f"     Secret '{secret_name}' not found in account {account_id}. Already deleted or never existed.")

    except Exception as e:
        print(f"     ERROR: Failed to delete from account {account_id} in region {region}. Error: {e}")

def lambda_handler(event, context):
    """Main function for the Lambda."""
    config = get_config()
    secrets_to_process = get_secrets_to_process()

    for resource in secrets_to_process:
        secret_arn = resource["ResourceARN"]
        tags = resource.get("Tags", [])
        
        try:
            # Check for sync operations
            sync_targets = resolve_sync_targets(tags, config)
            delete_targets = resolve_delete_targets(tags, config)

            if not sync_targets and not delete_targets:
                print(f"Skipping secret {secret_arn}: no target accounts for sync or delete operations.")
                continue

            describe_response = secretsmanager.describe_secret(SecretId=secret_arn)
            secret_name = describe_response["Name"]

            # Process sync operations
            if sync_targets:
                print(f"Processing sync for secret {secret_arn} to {len(sync_targets)} target(s).")
                secret_response = secretsmanager.get_secret_value(SecretId=secret_arn)
                secret_value = secret_response["SecretString"]
                
                for account_id, region in sync_targets:
                    sync_to_single_account(account_id, region, secret_name, secret_value)

            # Process delete operations
            if delete_targets:
                print(f"Processing delete for secret {secret_arn} from {len(delete_targets)} target(s).")
                
                for account_id, region in delete_targets:
                    delete_from_single_account(account_id, region, secret_name)

        except Exception as e:
            print(f"ERROR: Could not process secret {secret_arn}. Error: {e}")

    return {
        "statusCode": 200,
        "body": json.dumps("Secret sync process completed.")
    }
