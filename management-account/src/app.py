
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
            secret_info = target_sm_client.describe_secret(SecretId=secret_name)
            
            # Check if target secret is marked for deletion
            if secret_info.get("DeletedDate"):
                print(f"     Secret '{secret_name}' is marked for deletion, restoring it first.")
                target_sm_client.restore_secret(SecretId=secret_name)
                print(f"     Restored secret '{secret_name}' from deletion.")
            
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

def mark_secret_for_deletion(account_id, region, secret_name, source_describe_response):
    """Mark secret for deletion in target account with same settings as source."""
    region_str = region if region else "the default region"
    print(f"  -> Marking secret '{secret_name}' for deletion in account {account_id} in {region_str}...")
    try:
        assumed_role = sts.assume_role(
            RoleArn=f"arn:aws:iam::{account_id}:role/{ROLE_TO_ASSUME}",
            RoleSessionName="SecretSyncDeletionSession"
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
            # Check if target secret exists
            target_sm_client.describe_secret(SecretId=secret_name)
            
            # Calculate recovery window from source secret
            deletion_date = source_describe_response.get("DeletionDate")
            deleted_date = source_describe_response.get("DeletedDate")
            
            if deletion_date and deleted_date:
                # Calculate recovery window in days
                recovery_window = (deletion_date - deleted_date).days
                recovery_window = max(7, min(30, recovery_window))  # AWS limits: 7-30 days
                
                target_sm_client.delete_secret(
                    SecretId=secret_name,
                    RecoveryWindowInDays=recovery_window
                )
                print(f"     Successfully marked secret '{secret_name}' for deletion with {recovery_window} day recovery window.")
            else:
                # Default recovery window if we can't calculate
                target_sm_client.delete_secret(
                    SecretId=secret_name,
                    RecoveryWindowInDays=30
                )
                print(f"     Successfully marked secret '{secret_name}' for deletion with default 30 day recovery window.")
                
        except target_sm_client.exceptions.ResourceNotFoundException:
            print(f"     Secret '{secret_name}' not found in target account, nothing to delete.")

    except Exception as e:
        print(f"     ERROR: Failed to mark secret for deletion in account {account_id}: {e}")

def cleanup_orphaned_secrets(account_id, managed_secrets):
    """Remove secrets in target account that are no longer managed by this tool."""
    print(f"Cleaning up orphaned secrets in account {account_id}...")
    try:
        assumed_role = sts.assume_role(
            RoleArn=f"arn:aws:iam::{account_id}:role/{ROLE_TO_ASSUME}",
            RoleSessionName="SecretSyncCleanupSession"
        )
        credentials = assumed_role["Credentials"]
        
        target_sm_client = boto3.client(
            "secretsmanager",
            aws_access_key_id=credentials["AccessKeyId"],
            aws_secret_access_key=credentials["SecretAccessKey"],
            aws_session_token=credentials["SessionToken"],
        )

        # List all secrets managed by us
        response = target_sm_client.list_secrets(
            Filters=[
                {"Key": "tag-key", "Values": ["SyncedFrom"]},
                {"Key": "tag-value", "Values": [MANAGEMENT_ACCOUNT_ID]}
            ]
        )
        
        for secret in response.get("SecretList", []):
            secret_name = secret["Name"]
            if secret_name not in managed_secrets:
                print(f"  -> Deleting orphaned secret '{secret_name}' from account {account_id}")
                try:
                    target_sm_client.delete_secret(SecretId=secret_name, ForceDeleteWithoutRecovery=True)
                    print(f"     Successfully deleted orphaned secret '{secret_name}'")
                except Exception as e:
                    print(f"     ERROR: Failed to delete secret '{secret_name}': {e}")

    except Exception as e:
        print(f"ERROR: Failed to cleanup account {account_id}. Error: {e}")

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
    
    # Track which secrets should exist in each target account
    target_accounts = set()
    managed_secrets_per_account = {}

    for resource in secrets_to_process:
        secret_arn = resource["ResourceARN"]
        tags = resource.get("Tags", [])
        
        try:
            sync_targets = resolve_sync_targets(tags, config)

            if not sync_targets:
                print(f"Skipping secret {secret_arn}: no target accounts after calculating rules.")
                continue

            print(f"Processing secret {secret_arn} for {len(sync_targets)} target(s).")

            describe_response = secretsmanager.describe_secret(SecretId=secret_arn)
            secret_name = describe_response["Name"]
            
            # Check if secret is marked for deletion
            if describe_response.get("DeletedDate"):
                print(f"Secret '{secret_name}' is marked for deletion, syncing deletion state to targets.")
                # Track managed secrets for cleanup
                for account_id, region in sync_targets:
                    target_accounts.add(account_id)
                    if account_id not in managed_secrets_per_account:
                        managed_secrets_per_account[account_id] = set()
                    managed_secrets_per_account[account_id].add(secret_name)
                    
                    mark_secret_for_deletion(account_id, region, secret_name, describe_response)
            else:
                secret_response = secretsmanager.get_secret_value(SecretId=secret_arn)
                secret_value = secret_response["SecretString"]
                
                # Track managed secrets for cleanup
                for account_id, region in sync_targets:
                    target_accounts.add(account_id)
                    if account_id not in managed_secrets_per_account:
                        managed_secrets_per_account[account_id] = set()
                    managed_secrets_per_account[account_id].add(secret_name)
                    
                    sync_to_single_account(account_id, region, secret_name, secret_value)

        except Exception as e:
            print(f"ERROR: Could not process secret {secret_arn}. Error: {e}")

    # Cleanup phase: remove orphaned secrets
    for account_id in target_accounts:
        managed_secrets = managed_secrets_per_account.get(account_id, set())
        cleanup_orphaned_secrets(account_id, managed_secrets)

    return {
        "statusCode": 200,
        "body": json.dumps("Secret sync and cleanup process completed.")
    }
