# Edge (decision #2): Cloudflare (DNS + Universal SSL edge termination) → ALB
# with an ACM cert (Full (strict)). The ALB stays the path router:
# /api/* → API service, everything else → UI service.

resource "aws_lb" "main" {
  name               = "${var.project}-${var.environment}-${var.aws_region_tag}"
  load_balancer_type = "application"
  subnets            = aws_subnet.public[*].id
  security_groups    = [aws_security_group.alb.id]

  tags = { Name = "${var.project}-${var.environment}-alb" }
}

# Edge terminates TLS; the ALB still needs its own cert for Full (strict).
resource "aws_acm_certificate" "main" {
  domain_name       = var.domain_name
  validation_method = "DNS"

  tags = { Name = "${var.project}-${var.environment}-cert" }
}

# DNS records live in the owner's Cloudflare zone: the validation records the
# cert needs, then the alias-style CNAME pointing the domain at the ALB
# (proxied, so Universal SSL terminates at the edge).
locals {
  cert_validation_records = {
    for dvo in aws_acm_certificate.main.domain_validation_options :
    dvo.domain_name => {
      name  = dvo.resource_record_name
      value = dvo.resource_record_value
    }
  }
}

resource "cloudflare_dns_record" "cert_validation" {
  for_each = local.cert_validation_records

  zone_id = var.cloudflare_zone_id
  name    = each.value.name
  type    = "CNAME"
  content = each.value.value
  ttl     = 300
  proxied = false
}

resource "cloudflare_dns_record" "alb" {
  zone_id = var.cloudflare_zone_id
  name    = var.domain_name
  type    = "CNAME"
  content = aws_lb.main.dns_name
  ttl     = 1
  proxied = true
}

resource "aws_acm_certificate_validation" "main" {
  certificate_arn = aws_acm_certificate.main.arn
  depends_on      = [cloudflare_dns_record.cert_validation]
}

resource "aws_lb_target_group" "api" {
  name        = "${var.project}-${var.environment}-api"
  port        = 8000
  protocol    = "HTTP"
  target_type = "ip"
  vpc_id      = aws_vpc.main.id

  health_check {
    path                = "/api/healthz" # root_path=/api strips the prefix inside the task
    matcher             = "200-299"
    interval            = 30
    healthy_threshold   = 2
    unhealthy_threshold = 5
  }

  deregistration_delay = 30

  tags = { Name = "${var.project}-${var.environment}-api" }
}

resource "aws_lb_target_group" "ui" {
  name        = "${var.project}-${var.environment}-ui"
  port        = 3000
  protocol    = "HTTP"
  target_type = "ip"
  vpc_id      = aws_vpc.main.id

  health_check {
    path                = "/"
    matcher             = "200-399"
    interval            = 30
    healthy_threshold   = 2
    unhealthy_threshold = 5
  }

  deregistration_delay = 30

  tags = { Name = "${var.project}-${var.environment}-ui" }
}

resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.main.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type = "redirect"
    redirect {
      port        = "443"
      protocol    = "HTTPS"
      status_code = "HTTP_301"
    }
  }
}

resource "aws_lb_listener" "https" {
  load_balancer_arn = aws_lb.main.arn
  port              = 443
  protocol          = "HTTPS"
  ssl_policy        = "ELBSecurityPolicy-TLS13-1-2-2021-06"
  certificate_arn   = aws_acm_certificate.main.arn

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.ui.arn
  }

  # API traffic is distinguished by path; nothing else reaches the API.
  depends_on = [aws_acm_certificate_validation.main]
}

resource "aws_lb_listener_rule" "api" {
  listener_arn = aws_lb_listener.https.arn
  priority     = 10

  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.api.arn
  }

  condition {
    path_pattern {
      values = ["/api/*"]
    }
  }
}
