# IAM (decision #9's OIDC role lives in the GitHub workflow config, not here):
# task execution role (pull ECR, logs, read the SSM SecureStrings) — the
# tasks themselves need no AWS API access (EFS is mounted with IAM
# authorization disabled; the access point's POSIX user is the authority).

data "aws_iam_policy_document" "ecs_assume" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "task_execution" {
  name               = "${var.project}-${var.environment}-task-exec"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume.json
}

resource "aws_iam_role_policy_attachment" "task_execution_managed" {
  role       = aws_iam_role.task_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

# SecureString reads need kms:Decrypt on the default aws/ssm key.
data "aws_iam_policy_document" "task_execution_secrets" {
  statement {
    actions = [
      "ssm:GetParameters",
    ]

    resources = [
      aws_ssm_parameter.database_url.arn,
      aws_ssm_parameter.openai_api_key.arn,
      aws_ssm_parameter.sentry_dsn.arn,
    ]
  }

  statement {
    actions = ["kms:Decrypt"]

    resources = [data.aws_kms_alias.ssm.target_key_arn]
  }
}

data "aws_kms_alias" "ssm" {
  name = "alias/aws/ssm"
}

resource "aws_iam_role_policy" "task_execution_secrets" {
  name   = "read-task-secrets"
  role   = aws_iam_role.task_execution.id
  policy = data.aws_iam_policy_document.task_execution_secrets.json
}
