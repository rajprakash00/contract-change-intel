# ECR repos (decision #1/#9): one per service image. CI pushes immutable
# sha-pinned tags and services roll to the new revision.

resource "aws_ecr_repository" "api" {
  name                 = "${var.project}/${var.environment}-api"
  image_tag_mutability = "IMMUTABLE"
  force_delete         = true # demo posture: teardown must not be blocked by images

  image_scanning_configuration {
    scan_on_push = true
  }
}

resource "aws_ecr_repository" "ui" {
  name                 = "${var.project}/${var.environment}-ui"
  image_tag_mutability = "IMMUTABLE"
  force_delete         = true

  image_scanning_configuration {
    scan_on_push = true
  }
}
