# Security groups (decision #3): ALB → task SGs → RDS 5432 (+ EFS 2049).

resource "aws_security_group" "alb" {
  name   = "${var.project}-${var.environment}-alb"
  vpc_id = aws_vpc.main.id

  ingress {
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Name = "${var.project}-${var.environment}-alb" }
}

# Shared by the api and worker tasks (worker accepts no traffic; sharing the
# SG keeps the chain flat). Egress is open so tasks reach Auth0's JWKS and
# OpenAI over HTTPS.
resource "aws_security_group" "api_tasks" {
  name   = "${var.project}-${var.environment}-api-tasks"
  vpc_id = aws_vpc.main.id

  ingress {
    from_port       = 8000
    to_port         = 8000
    protocol        = "tcp"
    security_groups = [aws_security_group.alb.id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Name = "${var.project}-${var.environment}-api-tasks" }
}

resource "aws_security_group" "ui_tasks" {
  name   = "${var.project}-${var.environment}-ui-tasks"
  vpc_id = aws_vpc.main.id

  ingress {
    from_port       = 3000
    to_port         = 3000
    protocol        = "tcp"
    security_groups = [aws_security_group.alb.id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Name = "${var.project}-${var.environment}-ui-tasks" }
}

resource "aws_security_group" "rds" {
  name   = "${var.project}-${var.environment}-rds"
  vpc_id = aws_vpc.main.id

  ingress {
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.api_tasks.id]
  }

  tags = { Name = "${var.project}-${var.environment}-rds" }
}

resource "aws_security_group" "efs" {
  name   = "${var.project}-${var.environment}-efs"
  vpc_id = aws_vpc.main.id

  ingress {
    from_port       = 2049
    to_port         = 2049
    protocol        = "tcp"
    security_groups = [aws_security_group.api_tasks.id]
  }

  tags = { Name = "${var.project}-${var.environment}-efs" }
}
