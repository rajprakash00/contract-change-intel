# ECS Fargate (decision #4): three services on one cluster — API (uvicorn),
# UI (Next standalone), worker (same API image, command override). Tasks get
# public IPs and egress via the internet gateway (no NAT).

resource "aws_cloudwatch_log_group" "task" {
  for_each = toset(["api", "ui", "worker", "migrate"])

  name              = "/ecs/${var.project}-${var.environment}-${each.key}"
  retention_in_days = 14
}

locals {
  api_environment = [
    { name = "ROOT_PATH", value = "/api" }, # ALB strips nothing; FastAPI serves under /api (docs/w6-decisions.md #6)
    { name = "DATA_DIR", value = "/data" },
    { name = "AUTH0_DOMAIN", value = var.auth0_domain },
    { name = "AUTH0_AUDIENCE", value = var.auth0_audience },
  ]

  api_secrets = [
    { name = "DATABASE_URL", valueFrom = aws_ssm_parameter.database_url.arn },
    { name = "OPENAI_API_KEY", valueFrom = aws_ssm_parameter.openai_api_key.arn },
  ]

  # transit_encryption_port is omitted on purpose: the EFS mount helper's own
  # port strategy applies; the EFS SG opens 2049 to the task SGs.
  efs_volume_config = {
    file_system_id     = aws_efs_file_system.main.id
    root_directory     = "/"
    transit_encryption = "ENABLED"
    access_point_id    = aws_efs_access_point.data.id
    iam                = "DISABLED" # access point POSIX user is the authority
  }
}

# EFS mount config shared verbatim by the api and worker task definitions
# (ADR-009): one namespace, so the worker reads what the API wrote.
locals {
  efs_mount_points = [
    { sourceVolume = "data", containerPath = "/data", readOnly = false },
  ]
}

resource "aws_ecs_cluster" "main" {
  name = "${var.project}-${var.environment}"

  setting {
    name  = "containerInsights"
    value = "disabled"
  }
}

# --- API ---

resource "aws_ecs_task_definition" "api" {
  family                   = "${var.project}-${var.environment}-api"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 256
  memory                   = 512
  execution_role_arn       = aws_iam_role.task_execution.arn

  container_definitions = jsonencode([
    {
      name         = "api"
      image        = "${aws_ecr_repository.api.repository_url}:${var.image_tag}"
      command      = ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
      portMappings = [{ containerPort = 8000, protocol = "tcp" }]
      environment  = local.api_environment
      secrets      = local.api_secrets
      mountPoints  = local.efs_mount_points
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.task["api"].name
          "awslogs-region"        = var.region
          "awslogs-stream-prefix" = "api"
        }
      }
      healthCheck = {
        command     = ["CMD-SHELL", "python -c \"import urllib.request; urllib.request.urlopen('http://localhost:8000/healthz')\" || exit 1"]
        interval    = 30
        timeout     = 5
        retries     = 3
        startPeriod = 30
      }
    }
  ])

  volume {
    name = "data"
    efs_volume_configuration {
      file_system_id     = local.efs_volume_config.file_system_id
      root_directory     = local.efs_volume_config.root_directory
      transit_encryption = local.efs_volume_config.transit_encryption
      authorization_config {
        access_point_id = local.efs_volume_config.access_point_id
        iam             = local.efs_volume_config.iam
      }
    }
  }
}

resource "aws_ecs_service" "api" {
  name            = "${var.project}-${var.environment}-api"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.api.arn
  desired_count   = var.api_desired_count
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = aws_subnet.public[*].id
    security_groups  = [aws_security_group.api_tasks.id]
    assign_public_ip = true
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.api.arn
    container_name   = "api"
    container_port   = 8000
  }

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  health_check_grace_period_seconds = 30

  # CI owns task-definition revisions from here on (sha image tags +
  # update-service); an apply must not roll the image back.
  lifecycle {
    ignore_changes = [task_definition]
  }

  depends_on = [aws_lb_listener.https] # don't create a service before its listener exists
}

# --- UI ---

resource "aws_ecs_task_definition" "ui" {
  family                   = "${var.project}-${var.environment}-ui"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 256
  memory                   = 512
  execution_role_arn       = aws_iam_role.task_execution.arn

  container_definitions = jsonencode([
    {
      name         = "ui"
      image        = "${aws_ecr_repository.ui.repository_url}:${var.image_tag}"
      command      = ["node", "server.js"]
      portMappings = [{ containerPort = 3000, protocol = "tcp" }]
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.task["ui"].name
          "awslogs-region"        = var.region
          "awslogs-stream-prefix" = "ui"
        }
      }
    }
  ])
}

resource "aws_ecs_service" "ui" {
  name            = "${var.project}-${var.environment}-ui"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.ui.arn
  desired_count   = var.ui_desired_count
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = aws_subnet.public[*].id
    security_groups  = [aws_security_group.ui_tasks.id]
    assign_public_ip = true
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.ui.arn
    container_name   = "ui"
    container_port   = 3000
  }

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  health_check_grace_period_seconds = 30

  lifecycle {
    ignore_changes = [task_definition]
  }

  depends_on = [aws_lb_listener.https]
}

# --- Worker ---

# Same API image, command overridden to the worker entrypoint (decision #4).
# Desired count 0 while idle; scaled to 1 only for ingestion/demo runs.
resource "aws_ecs_task_definition" "worker" {
  family                   = "${var.project}-${var.environment}-worker"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 256
  memory                   = 512
  execution_role_arn       = aws_iam_role.task_execution.arn

  container_definitions = jsonencode([
    {
      name        = "worker"
      image       = "${aws_ecr_repository.api.repository_url}:${var.image_tag}"
      command     = ["python", "-m", "app.worker"]
      environment = local.api_environment
      secrets     = local.api_secrets
      mountPoints = local.efs_mount_points
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.task["worker"].name
          "awslogs-region"        = var.region
          "awslogs-stream-prefix" = "worker"
        }
      }
    }
  ])

  volume {
    name = "data"
    efs_volume_configuration {
      file_system_id     = local.efs_volume_config.file_system_id
      root_directory     = local.efs_volume_config.root_directory
      transit_encryption = local.efs_volume_config.transit_encryption
      authorization_config {
        access_point_id = local.efs_volume_config.access_point_id
        iam             = local.efs_volume_config.iam
      }
    }
  }
}

resource "aws_ecs_service" "worker" {
  name            = "${var.project}-${var.environment}-worker"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.worker.arn
  desired_count   = var.worker_desired_count
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = aws_subnet.public[*].id
    security_groups  = [aws_security_group.api_tasks.id]
    assign_public_ip = true
  }

  lifecycle {
    ignore_changes = [task_definition] # scale-ups keep whatever revision CI last registered
  }
}

# One-off run-task from CI: `aws ecs run-task` with this definition before
# rolling new task revisions. Not tied to any service; migrations are never
# automatic.
resource "aws_ecs_task_definition" "migrate" {
  family                   = "${var.project}-${var.environment}-migrate"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 256
  memory                   = 512
  execution_role_arn       = aws_iam_role.task_execution.arn

  container_definitions = jsonencode([
    {
      name        = "migrate"
      image       = "${aws_ecr_repository.api.repository_url}:${var.image_tag}"
      command     = ["alembic", "upgrade", "head"]
      environment = local.api_environment
      secrets     = local.api_secrets
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.task["migrate"].name
          "awslogs-region"        = var.region
          "awslogs-stream-prefix" = "migrate"
        }
      }
    }
  ])
}
