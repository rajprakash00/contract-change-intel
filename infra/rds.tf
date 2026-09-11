# RDS PostgreSQL 17 (decision #6): db.t4g.micro, 20 GB gp3, single-AZ,
# private subnets. pgvector needs no extra work — the W3 migration runs
# CREATE EXTENSION IF NOT EXISTS vector, and RDS PG17 ships pgvector.

resource "random_password" "db_master" {
  length  = 32
  special = false
}

resource "aws_db_subnet_group" "main" {
  name       = "${var.project}-${var.environment}-db"
  subnet_ids = aws_subnet.private[*].id

  tags = { Name = "${var.project}-${var.environment}-db" }
}

resource "aws_db_instance" "main" {
  identifier     = "${var.project}-${var.environment}-pg"
  engine         = "postgres"
  engine_version = "17.11" # 17.4 is not offered in ap-south-1; latest PG17 there
  instance_class = "db.t4g.small" # micro repeatedly hit insufficient-capacity in ap-south-1

  allocated_storage = 20
  storage_type      = "gp3"
  db_name           = "cci"
  username          = "postgres"
  password          = random_password.db_master.result

  multi_az                = false
  publicly_accessible     = false
  skip_final_snapshot     = true # demo posture; teardown is the off switch (decision #11)
  deletion_protection     = false
  backup_retention_period = 7

  db_subnet_group_name   = aws_db_subnet_group.main.name
  vpc_security_group_ids = [aws_security_group.rds.id]

  tags = { Name = "${var.project}-${var.environment}-pg" }
}
