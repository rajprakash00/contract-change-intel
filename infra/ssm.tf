# Secrets (decision #7): SSM Parameter Store SecureStrings reaching tasks via
# the task-definition `secrets` block; plain env vars only for non-secrets.
# The OpenAI key placeholder is overwritten by the owner before first deploy:
#   aws ssm put-parameter --name /cci/prod/openai_api_key \
#     --type SecureString --value sk-... --overwrite

locals {
  ssm_prefix = "/${var.project}/${var.environment}"
}

resource "aws_ssm_parameter" "database_url" {
  name  = "${local.ssm_prefix}/database_url"
  type  = "SecureString"
  value = "postgresql+asyncpg://postgres:${random_password.db_master.result}@${aws_db_instance.main.address}:5432/cci"

  tags = { Environment = var.environment }
}

resource "aws_ssm_parameter" "openai_api_key" {
  # Placeholder until the owner overwrites it; the API surfaces a 503 for LLM
  # features with an unusable key rather than failing silently.
  name  = "${local.ssm_prefix}/openai_api_key"
  type  = "SecureString"
  value = "replace-me"

  tags = { Environment = var.environment }
}

resource "aws_ssm_parameter" "sentry_dsn" {
  # Public-safe value (browser SDKs ship DSNs too); SecureString keeps the
  # secrets posture uniform (decision #7). Empty disables capture app-side.
  name  = "${local.ssm_prefix}/sentry_dsn"
  type  = "SecureString"
  value = var.sentry_dsn

  tags = { Environment = var.environment }
}
