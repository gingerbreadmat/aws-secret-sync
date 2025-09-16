# AWS Secret Sync

A simple, cost-effective, and self-hosted solution for synchronizing secrets across multiple AWS accounts from a central management account.

## How it Works

This solution uses a "hub-and-spoke" model for secret management:

*   **Hub (Management Account):** A central AWS account hosts the core infrastructure. This includes an AWS Lambda function and a central configuration secret. The secrets that need to be distributed (the "source of truth") also reside in this account.
*   **Spokes (Target Accounts):** Any number of target AWS accounts can receive secrets. They are configured by deploying a simple IAM role named `SecretSyncRole` that trusts the management account's Lambda.
*   **Sync Logic:** The Lambda function runs on a schedule (e.g., once per hour). It reads a central configuration file to identify account groupings, scans for secrets that are tagged for syncing, and then assumes the `SecretSyncRole` in each target account to write the secret values.

---

## Quick Start

### 1. Deploy Management Account Infrastructure

Deploy the `template.yaml` file located in the `management-account/` directory using the AWS SAM CLI:

```bash
sam build
sam deploy --guided
```

### 2. Setup Target Account Access

In each target account, add the `SecretSyncRole` IAM role. 

**📋 [View IaC Examples →](IAC-EXAMPLES.md)**

### 3. Start Syncing Secrets

**Simple approach (no configuration needed):**
Tag any secret in your management account:
- Key: `SecretSync-SyncAccount`
- Value: `123456789012` (target account ID)

**Advanced approach (account groups):**
Create a configuration secret and use group tags.

**📖 [View Configuration Guide →](CONFIGURATION.md)**

---

## Key Features

### ✅ **Simple Setup**
- No configuration needed for basic use cases
- Individual account tagging for quick start
- Optional account groups for complex scenarios

### ✅ **Deletion Sync**
- Automatic cleanup when secrets are deleted
- Configurable deletion policies per account group
- Safety features with recovery windows

### ✅ **Safety Controls** 
- `NeverDelete` mode for ultimate protection
- Management account tracking on all synced secrets
- Group-level deletion control

### ✅ **Cross-Region Support**
- Regional configuration per account group
- Automatic region detection for individual accounts

---

## Documentation

| Document | Description |
|----------|-------------|
| **[Configuration Guide](CONFIGURATION.md)** | Configuration options, account groups, and safety settings |
| **[IaC Examples](IAC-EXAMPLES.md)** | CloudFormation, Terraform, CDK, Pulumi, SAM examples |
| **[Usage Guide](USAGE.md)** | Day-to-day operations, tagging, and troubleshooting |

---

## Support

If you find this tool useful, please consider supporting my work!

<a href="https://buymeacoffee.com/gingerbreadmat"><img src="https://cdn.buymeacoffee.com/buttons/v2/default-yellow.png" alt="Buy Me A Coffee" style="height: 60px !important;width: 217px !important;" ></a>