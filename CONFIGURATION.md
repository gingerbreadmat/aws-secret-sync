# Configuration Guide

This guide covers all configuration options for AWS Secret Sync, from simple setups to advanced multi-account scenarios with safety controls.

## Configuration Approaches

### Simple Setup (No Configuration Required)

For basic use cases where you only sync to specific accounts, **no configuration secret is needed**. Just tag your secrets directly:

- Key: `SecretSync-SyncAccount`  
- Value: `123456789012` (target account ID)

**When to use:** Perfect for simple setups with just a few target accounts.

### Advanced Setup (Account Groups)

For complex scenarios with many accounts or regional requirements, create a configuration secret named `secret-sync/config` in your management account.

**When to use:** Best for organizations with many accounts or complex regional requirements.

---

## Configuration Secret Structure

Create a secret named `secret-sync/config` in AWS Secrets Manager with the following JSON structure:

### Basic Example
```json
{
  "Version": "1.0",
  "AccountGroups": {
    "Production": {
      "Accounts": ["111111111111", "222222222222"],
      "Region": "us-east-1"
    },
    "Development": [
      "333333333333",
      "444444444444"
    ]
  }
}
```

### Advanced Example (All Features)
```json
{
  "Version": "1.0",
  "DeleteSync": true,
  "NeverDelete": false,
  "AccountGroups": {
    "Production-US": {
      "Accounts": ["111111111111", "222222222222"],
      "Region": "us-east-1",
      "DeleteSync": false
    },
    "Production-EU": {
      "Accounts": ["333333333333"],
      "Region": "eu-west-1", 
      "DeleteSync": false
    },
    "Development": {
      "Accounts": ["444444444444", "555555555555"],
      "DeleteSync": true
    },
    "Staging-Legacy": [
      "666666666666"
    ]
  }
}
```

---

## Configuration Options

### Global Settings

#### `DeleteSync` (boolean, default: `true`)
Controls whether deletion operations are synchronized by default.

- `true` - Sync deletions and restorations (default behavior)
- `false` - Only sync active secrets, ignore deletion states

#### `NeverDelete` (boolean, default: `false`)
Ultimate safety override that prevents immediate deletions.

- `true` - All deletions use 7-day recovery window (no immediate deletions)
- `false` - Normal deletion behavior with calculated recovery windows

### Account Groups

Account groups allow you to organize target accounts and apply consistent settings.

#### Group Formats

**Object Format (Recommended):**
```json
"GroupName": {
  "Accounts": ["111111111111", "222222222222"],
  "Region": "us-east-1",
  "DeleteSync": false
}
```

**Array Format (Legacy):**
```json
"GroupName": ["111111111111", "222222222222"]
```

#### Group Settings

- **`Accounts`** (required) - Array of 12-digit AWS account IDs
- **`Region`** (optional) - AWS region for this group. If not specified, uses Lambda's region
- **`DeleteSync`** (optional) - Override global DeleteSync setting for this group

---

## Configuration Hierarchy

Settings are applied in the following priority order:

1. **Group-specific settings** (highest priority)
2. **Global settings** 
3. **Default values** (lowest priority)

### Examples

#### Global DeleteSync with Group Override
```json
{
  "DeleteSync": true,
  "AccountGroups": {
    "Production": {
      "Accounts": ["111111111111"],
      "DeleteSync": false
    },
    "Development": {
      "Accounts": ["222222222222"]
    }
  }
}
```

**Result:** 
- Production account: DeleteSync disabled
- Development account: DeleteSync enabled (inherits global setting)

#### NeverDelete Override
```json
{
  "DeleteSync": true,
  "NeverDelete": true,
  "AccountGroups": {
    "Production": {
      "Accounts": ["111111111111"],
      "DeleteSync": true
    }
  }
}
```

**Result:** 
- All deletions use 7-day recovery window regardless of other settings
- NeverDelete overrides everything for maximum safety

---

## Regional Configuration

### Same Region (Default)
If no region is specified, secrets sync to the same region as the Lambda function.

```json
"Development": {
  "Accounts": ["111111111111"]
}
```

### Cross-Region Sync
Specify a different region for the group:

```json
"Production-EU": {
  "Accounts": ["111111111111"],
  "Region": "eu-west-1"
}
```

### Multi-Region Setup
Create separate groups for each region:

```json
{
  "AccountGroups": {
    "Production-US": {
      "Accounts": ["111111111111"],
      "Region": "us-east-1"
    },
    "Production-EU": {
      "Accounts": ["111111111111"], 
      "Region": "eu-west-1"
    }
  }
}
```

---

## Safety Recommendations

### Production Environments
```json
{
  "NeverDelete": true,
  "AccountGroups": {
    "Production": {
      "Accounts": ["111111111111"],
      "DeleteSync": false
    }
  }
}
```

**Benefits:**
- Production secrets never get deleted automatically
- 7-day recovery window for any accidental deletions
- Manual control over production secret lifecycle

### Development Environments  
```json
{
  "DeleteSync": true,
  "AccountGroups": {
    "Development": {
      "Accounts": ["222222222222"],
      "DeleteSync": true
    }
  }
}
```

**Benefits:**
- Full sync including deletions for rapid development
- Automatic cleanup of removed secrets
- Matches source account behavior exactly

### Mixed Environments
```json
{
  "DeleteSync": false,
  "NeverDelete": false,
  "AccountGroups": {
    "Production": {
      "Accounts": ["111111111111"],
      "DeleteSync": false
    },
    "Staging": {
      "Accounts": ["222222222222"],
      "DeleteSync": true
    },
    "Development": {
      "Accounts": ["333333333333"],
      "DeleteSync": true
    }
  }
}
```

**Benefits:**
- Production: No automatic deletions
- Staging/Dev: Full sync including deletions
- Granular control per environment type

---

## Migration Guide

### From Simple to Advanced Setup

**Current (Simple):**
- Using `SecretSync-SyncAccount` tags only
- No configuration secret

**Migration Steps:**
1. Create `secret-sync/config` secret
2. Define account groups
3. Update secret tags to use `SecretSync-SyncDestinationGroup`
4. Remove old `SecretSync-SyncAccount` tags

**No downtime required** - both approaches work simultaneously.

### Adding Safety Controls

**Step 1:** Enable global safety
```json
{
  "DeleteSync": true,
  "NeverDelete": true
}
```

**Step 2:** Configure per-environment policies
```json
{
  "DeleteSync": true,
  "NeverDelete": false,
  "AccountGroups": {
    "Production": {"DeleteSync": false},
    "Development": {"DeleteSync": true}
  }
}
```

---

## Troubleshooting

### Configuration Not Loading
- Verify secret name is exactly `secret-sync/config`
- Check JSON syntax with a validator
- Ensure Lambda has `secretsmanager:GetSecretValue` permission

### Group Tags Not Working
- Verify group names match exactly (case-sensitive)
- Check that configuration secret exists when using group tags
- Review CloudWatch logs for specific error messages

### Deletion Sync Issues
- Check `DeleteSync` settings at global and group levels
- Verify target account has `secretsmanager:DeleteSecret` permission  
- Review `NeverDelete` setting if deletions seem to have recovery windows

### Regional Issues
- Verify region names are valid AWS regions
- Check that target accounts have the role in the specified region
- Remember: individual account tags always use Lambda's region