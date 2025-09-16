# Usage Guide

This guide covers day-to-day operations, tagging strategies, and troubleshooting for AWS Secret Sync.

## Tagging Reference

AWS Secret Sync uses tags on secrets in your management account to control sync behavior. There are two approaches:

### Simple Tagging (No Configuration)
For basic use cases, tag secrets directly with target accounts:

| Tag Key | Tag Value | Purpose |
|---------|-----------|---------|
| `SecretSync-SyncAccount` | `123456789012` | Sync to specific account |
| `SecretSync-NoSyncAccount` | `123456789012` | Exclude specific account |

### Advanced Tagging (With Configuration)
For complex scenarios using account groups:

| Tag Key | Tag Value | Purpose |
|---------|-----------|---------|
| `SecretSync-SyncDestinationGroup` | `Production` | Sync to all accounts in group |
| `SecretSync-NoSyncDestinationGroup` | `Production` | Exclude all accounts in group |
| `SecretSync-SyncAccount` | `123456789012` | Add specific account to sync list |
| `SecretSync-NoSyncAccount` | `123456789012` | Exclude specific account |

---

## Common Scenarios

### Sync to Single Account
**Goal:** Sync a secret to one specific account

**Tags:**
- Key: `SecretSync-SyncAccount`
- Value: `123456789012`

### Sync to Multiple Specific Accounts
**Goal:** Sync to accounts A, B, and C only

**Option 1 (Simple):** Use multiple `SecretSync-SyncAccount` tags
- Key: `SecretSync-SyncAccount`, Value: `111111111111`
- Key: `SecretSync-SyncAccount`, Value: `222222222222` 
- Key: `SecretSync-SyncAccount`, Value: `333333333333`

**Option 2 (Advanced):** Create an account group in config
```json
{
  "AccountGroups": {
    "MySpecificAccounts": {
      "Accounts": ["111111111111", "222222222222", "333333333333"]
    }
  }
}
```

**Tag:**
- Key: `SecretSync-SyncDestinationGroup`
- Value: `MySpecificAccounts`

### Sync to All Production Except One
**Goal:** Sync to all production accounts except staging

**Prerequisites:** Account groups configured
```json
{
  "AccountGroups": {
    "Production": {
      "Accounts": ["111111111111", "222222222222", "333333333333"]
    }
  }
}
```

**Tags:**
- Key: `SecretSync-SyncDestinationGroup`, Value: `Production`
- Key: `SecretSync-NoSyncAccount`, Value: `333333333333`

### Sync to Group Plus Extra Account
**Goal:** Sync to Development group + one special account

**Tags:**
- Key: `SecretSync-SyncDestinationGroup`, Value: `Development`
- Key: `SecretSync-SyncAccount`, Value: `999999999999`

### Cross-Region Sync
**Goal:** Sync to specific region

**Prerequisites:** Account group with region specified
```json
{
  "AccountGroups": {
    "Production-EU": {
      "Accounts": ["111111111111"],
      "Region": "eu-west-1"
    }
  }
}
```

**Tag:**
- Key: `SecretSync-SyncDestinationGroup`
- Value: `Production-EU`

**Note:** Individual account tags (`SecretSync-SyncAccount`) always use the Lambda's region.

---

## Deletion Management

### Delete Secret Everywhere
**Goal:** Remove secret from management account and all target accounts

**Steps:**
1. Delete secret in management account (AWS Console or CLI)
2. Wait for next Lambda run (or trigger manually)
3. Target account secrets will be marked for deletion automatically

**Behavior depends on configuration:**
- `DeleteSync: true` → Target secrets marked for deletion with recovery window
- `DeleteSync: false` → Target secrets remain untouched
- `NeverDelete: true` → All deletions use 7-day recovery window

### Delete from Specific Accounts Only
**Goal:** Remove secret from some accounts but keep in others

**Method:** Update tags to exclude specific accounts:
- Add `SecretSync-NoSyncAccount` tags for accounts to remove from
- Keep existing sync tags for accounts to maintain

**Next sync will:**
- Remove secret from excluded accounts (if DeleteSync enabled)
- Continue syncing to remaining accounts

### Cancel Deletion (Restore)
**Goal:** Restore a deleted secret

**Steps:**
1. Restore secret in management account
2. Wait for next Lambda run (or trigger manually)  
3. Target account secrets will be restored automatically (if DeleteSync enabled)

---

## Monitoring and Troubleshooting

### Check Lambda Logs
View CloudWatch logs for the `SecretSyncFunction`:

1. Go to AWS CloudWatch Console
2. Navigate to Log Groups
3. Find `/aws/lambda/SecretSyncFunction` (or your stack name)
4. Review recent log streams

### Common Log Messages

#### Success Messages
```
Successfully loaded configuration.
Found 5 secrets with sync-related tags.
Processing secret arn:aws:secretsmanager:...
  -> Syncing to account 123456789012...
     Successfully updated secret 'my-secret' in account 123456789012.
```

#### Configuration Issues
```
FATAL: Configuration secret secret-sync/config not found.
Configuration secret secret-sync/config not found. Using individual account tags only.
```

#### Permission Issues
```
ERROR: Failed to sync to account 123456789012. Error: AccessDenied
ERROR: Failed to cleanup account 123456789012. Error: AccessDenied
```

#### Tag Issues
```
Found 0 secrets with sync-related tags.
Skipping secret arn:aws:secretsmanager:...: no target accounts after calculating rules.
```

### Manual Trigger
To trigger the Lambda manually for immediate sync:

1. Go to AWS Lambda Console
2. Find your `SecretSyncFunction`
3. Click "Test" 
4. Use any test event (content doesn't matter)
5. Click "Test" to execute

### Validation Checklist

#### Secret Not Syncing
- [ ] Secret has correct sync tags (`SecretSync-SyncAccount` or `SecretSync-SyncDestinationGroup`)
- [ ] Tag values match account IDs or group names exactly
- [ ] If using groups, configuration secret exists and has correct group definition
- [ ] Target account has `SecretSyncRole` with correct permissions
- [ ] Target account role trusts the management account Lambda role

#### Secret Not Deleting
- [ ] `DeleteSync` is enabled (global or group level)
- [ ] `NeverDelete` is not preventing deletions
- [ ] Target account has `secretsmanager:DeleteSecret` permission
- [ ] Secret was originally synced by this tool (has `SyncedFrom` tag)

#### Restoration Not Working
- [ ] Source secret has been restored in management account
- [ ] `DeleteSync` is enabled for the target account
- [ ] Target account has `secretsmanager:RestoreSecret` permission

---

## Best Practices

### Tagging Strategy
- **Use descriptive group names** that clearly indicate purpose (e.g., `Production-US`, `Development-All`)
- **Prefer groups over individual tags** for maintainability
- **Document your tagging strategy** in your team's runbook
- **Use consistent naming** across all secrets and groups

### Secret Management
- **Tag secrets when created** to avoid manual sync gaps
- **Remove tags before deleting** if you want to keep target copies
- **Test with non-production secrets** before applying to production
- **Monitor CloudWatch logs** regularly for issues

### Safety Practices
- **Enable `NeverDelete`** during sensitive operations
- **Disable `DeleteSync`** for production groups initially
- **Use recovery windows** appropriate for your change management process
- **Test restoration procedures** before you need them

### Regional Considerations
- **Group accounts by region** when using cross-region sync
- **Understand region inheritance** (individual tags use Lambda's region)
- **Monitor costs** for cross-region data transfer
- **Consider latency** for time-sensitive secrets

---

## Advanced Usage

### Conditional Sync Based on Environment
Use different tagging strategies per environment:

**Development Secrets:**
- Tag: `SecretSync-SyncDestinationGroup: Development`
- Config: `"Development": {"DeleteSync": true}`
- Result: Full sync including deletions

**Production Secrets:**
- Tag: `SecretSync-SyncDestinationGroup: Production`  
- Config: `"Production": {"DeleteSync": false}`
- Result: Sync values only, manual deletion control

### Disaster Recovery Setup
Sync critical secrets to DR regions:

```json
{
  "AccountGroups": {
    "Production-Primary": {
      "Accounts": ["111111111111"],
      "Region": "us-east-1"
    },
    "Production-DR": {
      "Accounts": ["111111111111"],
      "Region": "us-west-2"
    }
  }
}
```

**Tags:**
- Key: `SecretSync-SyncDestinationGroup`, Value: `Production-Primary`
- Key: `SecretSync-SyncDestinationGroup`, Value: `Production-DR`

### Gradual Rollout Strategy
1. **Start simple:** Use individual account tags
2. **Add groups:** Create account groups for common patterns
3. **Enable deletion sync:** Start with non-production
4. **Add safety controls:** Configure `NeverDelete` for production
5. **Monitor and adjust:** Refine based on operational experience

### Integration with CI/CD
Automate secret tagging in your deployment pipeline:

```bash
# Tag secret for development deployment
aws secretsmanager tag-resource \
  --secret-id "my-app/database-password" \
  --tags Key=SecretSync-SyncDestinationGroup,Value=Development

# Remove tag for production cleanup
aws secretsmanager untag-resource \
  --secret-id "my-app/database-password" \
  --tag-keys SecretSync-SyncDestinationGroup
```