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
    """
    Finds all secrets that have at least one of our sync tags.
    The get_resources API doesn't support OR on tags, so we must fetch all
    secrets and filter them in the code.
    """
    print("Searching for all secrets to find resources to process...")
    paginator = tagging.get_paginator("get_resources")
    pages = paginator.paginate(ResourceTypeFilters=["secretsmanager:secret"])
    
    secrets_to_process = []
    for page in pages:
        for resource in page.get("ResourceTagMappingList", []):
            # Check if any of the resource's tags match our sync tag keys
            if any(tag['Key'] in SYNC_TAG_KEYS for tag in resource.get("Tags", [])):
                secrets_to_process.append(resource)
            
    print(f"Found {len(secrets_to_process)} secrets with sync-related tags.")
    return secrets_to_process

def calculate_target_accounts(tags, config):
    """
    Calculates the final set of target accounts based on the logic:
    (Sync Groups + Sync Accounts) - (NoSync Groups + NoSync Accounts)
    """
    sync_set = set()
    exclude_set = set()
    account_groups = config.get("AccountGroups", {})

    for tag in tags:
        key = tag.get("Key")
        value = tag.get("Value")

        if key == TAG_SYNC_GROUP:
            sync_set.update(account_groups.get(value, []))
        elif key == TAG_SYNC_ACCOUNT:
            sync_set.add(value)
        elif key == TAG_NO_SYNC_GROUP:
            exclude_set.update(account_groups.get(value, []))
        elif key == TAG_NO_SYNC_ACCOUNT:
            exclude_set.add(value)
            
    return sync_set - exclude_set

def sync_to_single_account(account_id, secret_name, secret_value):
    """Assumes a role in a target account and creates/updates the secret."""
    print(f"  -> Syncing to account {account_id} as secret '{secret_name}'...")
    try:
        assumed_role = sts.assume_role(
            RoleArn=f"arn:aws:iam::{account_id}:role/{ROLE_TO_ASSUME}",
            RoleSessionName="SecretSyncSession"
        )
        credentials = assumed_role["Credentials"]
        
        target_sm_client = boto3.client(
            "secretsmanager",
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
        print(f"     ERROR: Failed to sync to account {account_id}. Error: {e}")

def lambda_handler(event, context):
    """Main function for the Lambda."""
    config = get_config()
    secrets_to_process = get_secrets_to_process()

    for resource in secrets_to_process:
        secret_arn = resource["ResourceARN"]
        tags = resource.get("Tags", [])
        
        try:
            # Determine the final list of accounts to sync to
            final_accounts = calculate_target_accounts(tags, config)

            if not final_accounts:
                print(f"Skipping secret {secret_arn}: no target accounts after calculating exclusions.")
                continue

            print(f"Processing secret {secret_arn} for {len(final_accounts)} target account(s).")

            # Get the secret's name and value
            describe_response = secretsmanager.describe_secret(SecretId=secret_arn)
            secret_name = describe_response["Name"]
            secret_response = secretsmanager.get_secret_value(SecretId=secret_arn)
            secret_value = secret_response["SecretString"]
            
            # Sync to each final account
            for account_id in final_accounts:
                sync_to_single_account(account_id, secret_name, secret_value)

        except Exception as e:
            print(f"ERROR: Could not process secret {secret_arn}. Error: {e}")

    return {
        "statusCode": 200,
        "body": json.dumps("Secret sync process completed.")
    }