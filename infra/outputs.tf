output "alb_dns_name" {
  description = "Target for the Cloudflare CNAME (already created via cloudflare_dns_record.alb)."
  value       = aws_lb.main.dns_name
}

output "public_url" {
  description = "Same-origin entry point for the deployed UI and API."
  value       = "https://${var.domain_name}"
}

output "api_url" {
  description = "API base under the ALB path router."
  value       = "https://${var.domain_name}/api"
}

output "ecr_api_repository_url" {
  value = aws_ecr_repository.api.repository_url
}

output "ecr_ui_repository_url" {
  value = aws_ecr_repository.ui.repository_url
}

output "rds_endpoint" {
  value = aws_db_instance.main.address
}

output "ssm_parameter_names" {
  description = "SecureStrings the tasks read (openai_api_key is a placeholder until the owner overwrites it)."
  value = {
    database_url   = aws_ssm_parameter.database_url.name
    openai_api_key = aws_ssm_parameter.openai_api_key.name
    sentry_dsn     = aws_ssm_parameter.sentry_dsn.name
  }
}

output "migrate_task_family" {
  description = "Family CI runs as the one-off migration task."
  value       = aws_ecs_task_definition.migrate.family
}

output "ecs_cluster_name" {
  value = aws_ecs_cluster.main.name
}

output "public_subnet_ids" {
  description = "Network config for the migration run-task (public subnets, public IP)."
  value       = aws_subnet.public[*].id
}

output "api_task_security_group_id" {
  description = "Security group for the migration task (shares the api/worker task SG)."
  value       = aws_security_group.api_tasks.id
}
