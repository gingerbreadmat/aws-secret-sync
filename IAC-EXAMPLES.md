# Infrastructure as Code Examples

This document provides examples for implementing the required `SecretSyncRole` in various Infrastructure as Code (IaC) tools.

## Required Permissions

All examples implement the same IAM role with these permissions:

**Trust Policy** (replace `YOUR_MANAGEMENT_ACCOUNT_ID`):
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "AWS": "arn:aws:iam::YOUR_MANAGEMENT_ACCOUNT_ID:role/SecretSyncLambdaRole"
      },
      "Action": "sts:AssumeRole"
    }
  ]
}
```

**Permissions Policy**:
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "secretsmanager:CreateSecret",
        "secretsmanager:UpdateSecret", 
        "secretsmanager:PutSecretValue",
        "secretsmanager:DescribeSecret",
        "secretsmanager:TagResource",
        "secretsmanager:ListSecrets",
        "secretsmanager:DeleteSecret",
        "secretsmanager:RestoreSecret"
      ],
      "Resource": "*"
    }
  ]
}
```

---

## CloudFormation

Add the following to your existing CloudFormation template:

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
                  - "secretsmanager:TagResource"
                  - "secretsmanager:ListSecrets"
                  - "secretsmanager:DeleteSecret"
                  - "secretsmanager:RestoreSecret"
                Resource: "*"
```

---

## Terraform

Add the following to your existing Terraform configuration:

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
          "secretsmanager:DescribeSecret",
          "secretsmanager:TagResource",
          "secretsmanager:ListSecrets",
          "secretsmanager:DeleteSecret",
          "secretsmanager:RestoreSecret"
        ],
        Resource = "*"
      }
    ]
  })
}
```

---

## AWS CDK (TypeScript)

Add the following to your existing CDK stack:

```typescript
import { Role, PolicyStatement, Effect, ServicePrincipal } from 'aws-cdk-lib/aws-iam';

const managementAccountId = 'YOUR_MANAGEMENT_ACCOUNT_ID'; // Replace with actual ID

const secretSyncRole = new Role(this, 'SecretSyncRole', {
  roleName: 'SecretSyncRole',
  assumedBy: new ServicePrincipal(`arn:aws:iam::${managementAccountId}:role/SecretSyncLambdaRole`),
});

secretSyncRole.addToPolicy(new PolicyStatement({
  effect: Effect.ALLOW,
  actions: [
    'secretsmanager:CreateSecret',
    'secretsmanager:UpdateSecret',
    'secretsmanager:PutSecretValue',
    'secretsmanager:DescribeSecret',
    'secretsmanager:TagResource',
    'secretsmanager:ListSecrets',
    'secretsmanager:DeleteSecret',
    'secretsmanager:RestoreSecret'
  ],
  resources: ['*']
}));
```

---

## Pulumi (TypeScript)

Add the following to your existing Pulumi program:

```typescript
import * as aws from "@pulumi/aws";

const managementAccountId = 'YOUR_MANAGEMENT_ACCOUNT_ID'; // Replace with actual ID

const secretSyncRole = new aws.iam.Role("secretSyncRole", {
    name: "SecretSyncRole",
    assumeRolePolicy: JSON.stringify({
        Version: "2012-10-17",
        Statement: [{
            Effect: "Allow",
            Principal: {
                AWS: `arn:aws:iam::${managementAccountId}:role/SecretSyncLambdaRole`
            },
            Action: "sts:AssumeRole"
        }]
    })
});

const secretSyncPolicy = new aws.iam.RolePolicy("secretSyncPolicy", {
    name: "SecretWriteAccess",
    role: secretSyncRole.id,
    policy: JSON.stringify({
        Version: "2012-10-17",
        Statement: [{
            Effect: "Allow",
            Action: [
                "secretsmanager:CreateSecret",
                "secretsmanager:UpdateSecret",
                "secretsmanager:PutSecretValue",
                "secretsmanager:DescribeSecret",
                "secretsmanager:TagResource",
                "secretsmanager:ListSecrets",
                "secretsmanager:DeleteSecret",
                "secretsmanager:RestoreSecret"
            ],
            Resource: "*"
        }]
    })
});
```

---

## AWS SAM

Add the following to your existing SAM template:

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
                  - "secretsmanager:TagResource"
                  - "secretsmanager:ListSecrets"
                  - "secretsmanager:DeleteSecret"
                  - "secretsmanager:RestoreSecret"
                Resource: "*"
```

---

## Other IaC Tools

If you're using a different Infrastructure as Code tool not listed here, you can use the JSON policies at the top of this document as a reference for implementing the same permissions in your tool of choice.

The key requirements are:
- Role name must be exactly `SecretSyncRole`
- Trust the Lambda role in your management account
- Grant the four Secrets Manager permissions listed above