# AWS Secret Sync

A simple, cost-effective, and self-hosted solution for synchronizing secrets across multiple AWS accounts from a central management account.

## How it Works

This solution uses a "hub-and-spoke" model for secret management.

*   **Hub (Management Account):** A central AWS account hosts the core infrastructure. This includes an AWS Lambda function and a central configuration secret. The secrets that need to be distributed (the "source of truth") also reside in this account.
*   **Spokes (Target Accounts):** Any number of target AWS accounts can receive secrets. They are configured by deploying a simple IAM role named `SecretSyncRole` that trusts the management account's Lambda.
*   **Sync Logic:** The Lambda function runs on a schedule (e.g., once per hour). It reads a central configuration file to identify account groupings, scans for secrets that are tagged for syncing, and then assumes the `SecretSyncRole` in each target account to write the secret values.

*(Architecture Diagram to be created here)*

---

## Setup Instructions

### **Part 1: Management Account Setup (One-Time)**

1.  **Deploy the Stack:**
    *   Deploy the `template.yaml` file located in the `management-account/` directory of this project using the AWS SAM CLI.
    *   This will create the Secret Sync Lambda function and its associated execution role and trigger.

2.  **Create Configuration Secret:**
    *   In the AWS Secrets Manager console of your management account, create a new secret with the name `secret-sync/config`.
    *   The content of the secret should be a JSON object defining your account groups.

    **Example `secret-sync/config` JSON:**

    Each key in `AccountGroups` defines a group. The value can be a simple list of account IDs (for same-region syncing) or an object containing an `Accounts` list and an optional `Region`.

    ```json
    {
      "Version": "1.0",
      "AccountGroups": {
        "Production-US": {
          "Accounts": ["111111111111", "222222222222"],
          "Region": "us-east-1"
        },
        "Production-EU": {
          "Accounts": ["333333333333"],
          "Region": "eu-west-1"
        },
        "Dev-SameRegion": [
          "444444444444"
        ]
      }
    }
    ```

### **Part 2: Target Account Setup (One-Time)**

In each target account, you must add an IAM role named `SecretSyncRole` that the management account's Lambda can assume.

Instead of deploying a separate stack, we recommend adding this role to your existing Infrastructure as Code (IaC) setup. Below are examples for CloudFormation and Terraform.

---

#### **CloudFormation Example**

Add the following `Resource` to your existing CloudFormation template. You will need to pass in the `ManagementAccountId` as a parameter to your stack.

```yaml
Parameters:
  ManagementAccountId:
    Type: String
    Description: "The 12-digit AWS Account ID of the Secret Sync management account."

Resources:
  SecretSyncRole:
    Type: AWS::IAM::Role
    Properties:
      RoleName: SecretSyncRole
      AssumeRolePolicyDocument:
        Version: '2012-10-17'
        Statement:
          - Effect: Allow
            Principal:
              AWS: !Sub "arn:aws:iam::${ManagementAccountId}:role/SecretSyncLambdaRole"
            Action: "sts:AssumeRole"
      Policies:
        - PolicyName: SecretWriteAccess
          PolicyDocument:
            Version: '2012-10-17'
            Statement:
              - Effect: Allow
                Action:
                  - "secretsmanager:CreateSecret"
                  - "secretsmanager:UpdateSecret"
                  - "secretsmanager:PutSecretValue"
                  - "secretsmanager:DescribeSecret"
                Resource: "*"
```

---

#### **Terraform Example**

Add the following resources to your existing Terraform configuration. You will need to provide the `management_account_id` as a variable.

```hcl
variable "management_account_id" {
  description = "The 12-digit AWS Account ID of the Secret Sync management account."
  type        = string
}

resource "aws_iam_role" "secret_sync_role" {
  name = "SecretSyncRole"

  assume_role_policy = jsonencode({
    Version   = "2012-10-17",
    Statement = [
      {
        Effect    = "Allow",
        Principal = {
          AWS = "arn:aws:iam::${var.management_account_id}:role/SecretSyncLambdaRole"
        },
        Action    = "sts:AssumeRole"
      }
    ]
  })
}

resource "aws_iam_role_policy" "secret_write_access" {
  name = "SecretWriteAccess"
  role = aws_iam_role.secret_sync_role.id

  policy = jsonencode({
    Version   = "2012-10-17",
    Statement = [
      {
        Effect   = "Allow",
        Action = [
          "secretsmanager:CreateSecret",
          "secretsmanager:UpdateSecret",
          "secretsmanager:PutSecretValue",
          "secretsmanager:DescribeSecret"
        ],
        Resource = "*"
      }
    ]
  })
}
```

---

## Day-to-Day Usage

Tagging a secret in the management account is how you control where it gets synced. The logic is determined by a combination of four possible tags.

### Tagging Rules

1.  **Build a "Sync" list:**
    *   `SecretSync-SyncDestinationGroup`: Syncs the secret to all accounts in this group from your config file.
    *   `SecretSync-SyncAccount`: Syncs the secret to the single account ID specified.

2.  **Build a "NoSync" list:**
    *   `SecretSync-NoSyncDestinationGroup`: EXCLUDES all accounts in this group.
    *   `SecretSync-NoSyncAccount`: EXCLUDES the single account ID specified.

3.  **Final Logic:** The final list of accounts to sync to is (`Sync` list) - (`NoSync` list).
    *   **Exclusion takes priority.** If an account is in both lists, it will be excluded.
    *   The `...Account` tags only support a single account ID. To specify multiple accounts, you must create a group in the `secret-sync/config` file.

### Example Scenarios

#### Sync to All Except One Account

To sync a secret to the `all` group, but exclude account `123456789012`:

*   **Tag 1:**
    *   Key: `SecretSync-SyncDestinationGroup`
    *   Value: `all`
*   **Tag 2:**
    *   Key: `SecretSync-NoSyncAccount`
    *   Value: `123456789012`

#### Sync to a Group and One Extra Account

To sync a secret to the `Development` group and also to a special `Staging` account (`987654321098`):

*   **Tag 1:**
    *   Key: `SecretSync-SyncDestinationGroup`
    *   Value: `Development`
*   **Tag 2:**
    *   Key: `SecretSync-SyncAccount`
    *   Value: `987654321098`

### Triggering the Sync

After tagging a secret, the Lambda will process it on its next scheduled run (e.g., once per hour). You can also trigger the Lambda manually in the AWS Console for an immediate sync.

---

## Support

If you find this tool useful, please consider supporting my work!

<a href="https://buymeacoffee.com/gingerbreadmat"><img src="https://cdn.buymeacoffee.com/buttons/v2/default-yellow.png" alt="Buy Me A Coffee" style="height: 60px !important;width: 217px !important;" ></a>