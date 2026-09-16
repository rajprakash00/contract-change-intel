variable "region" {
  description = "AWS region for the stack; pinned to ap-south-1 (Mumbai) per owner decision, overriding the grill session's us-east-1 placeholder. backend.tf hardcodes the same region because the S3 backend block cannot use variables."
  type        = string
  default     = "ap-south-1"
}

variable "project" {
  description = "Name prefix for every resource."
  type        = string
  default     = "cci"
}

variable "environment" {
  description = "Deploy environment tag used in names and SSM paths."
  type        = string
  default     = "prod"
}

variable "domain_name" {
  description = "Public hostname the ALB answers on (Cloudflare zone covers this name)."
  type        = string
}

variable "cloudflare_zone_id" {
  description = "Cloudflare zone containing domain_name; the zone is created once by the owner."
  type        = string
}

# Desired counts (decision #4: API 1, UI 1, worker 0 — worker scales to 1 only
# for ingestion/demo runs; decision #11's idle-at-zero is a `terraform apply
# -var=api_desired_count=0 ...` or update-service away).
variable "api_desired_count" {
  type    = number
  default = 1
}

variable "ui_desired_count" {
  type    = number
  default = 1
}

variable "worker_desired_count" {
  type    = number
  default = 0
}

variable "image_tag" {
  description = "ECR tag baked into task definitions on first apply. CI registers later revisions with sha tags and calls update-service — task_definition is ignored on the services for that reason."
  type        = string
  default     = "bootstrap"
}

variable "auth0_domain" {
  description = "Auth0 tenant domain (non-secret; plain env var per decision #7)."
  type        = string
}

variable "auth0_audience" {
  description = "Auth0 API identifier (non-secret; plain env var per decision #7)."
  type        = string
}

variable "aws_region_tag" {
  description = "Region tag recorded in resource names to make cross-region drift visible."
  type        = string
  default     = "aps1"
}

variable "alert_email" {
  description = "Owner email for CloudWatch alarm notifications (SNS); the subscription stays pending until the confirmation mail is clicked."
  type        = string
  default     = ""
}

variable "sentry_dsn" {
  description = "Sentry DSN for unhandled-exception capture; empty disables capture (app treats an empty DSN as a no-op). Landing in an SSM SecureString consumed via the task secrets block."
  type        = string
  default     = ""
}
