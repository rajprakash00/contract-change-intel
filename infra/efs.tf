# EFS (decision #5, ADR-009): mounted at data_dir on API and worker tasks.
# The content-addressed layout {data_dir}/{tenant_id}/{sha256} is unchanged;
# the container user is pinned to UID 1000 (Dockerfile) to match the access
# point's POSIX user.

resource "aws_efs_file_system" "main" {
  creation_token = "${var.project}-${var.environment}-data"
  encrypted      = true

  throughput_mode = "elastic" # demo scale; no provisioned throughput standing cost

  tags = { Name = "${var.project}-${var.environment}-data" }
}

resource "aws_efs_mount_target" "main" {
  for_each = toset(aws_subnet.public[*].id)

  file_system_id  = aws_efs_file_system.main.id
  subnet_id       = each.value
  security_groups = [aws_security_group.efs.id]
}

resource "aws_efs_access_point" "data" {
  file_system_id = aws_efs_file_system.main.id

  root_directory {
    path = "/data"
    creation_info {
      owner_gid   = 1000
      owner_uid   = 1000
      permissions = "0755"
    }
  }

  posix_user {
    gid = 1000
    uid = 1000
  }

  tags = { Name = "${var.project}-${var.environment}-data-ap" }
}
