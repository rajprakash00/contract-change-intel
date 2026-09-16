# Observability (W6·C): alarms the demo checklist cannot be trusted to
# replace — the stuck-queued and placeholder-key incidents both produced log
# lines nobody was watching. Two layers:
#
#   1. Metric filters on the existing log groups (app emits JSON with stable
#      top-level keys: level/logger/message — app/logging_config.py).
#   2. SNS email alarms; the subscription needs one manual owner confirmation
#      click (AWS requirement, cannot be scripted).
#
# The audit_log table remains the system of record for audit history; these
# filters watch operational health, not the audit trail.

locals {
  metric_namespace = "CCI/${var.environment}"
}

# --- Alerts channel -----------------------------------------------------------

resource "aws_sns_topic" "alerts" {
  name = "${var.project}-${var.environment}-alerts"
  tags = { Environment = var.environment }
}

resource "aws_sns_topic_subscription" "alerts_email" {
  count     = var.alert_email != "" ? 1 : 0
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = var.alert_email
}

# --- Metric filters -----------------------------------------------------------

# Job failure signal: every service logs "<kind> job failed ..." and the
# attempt-cap terminal state as "<kind> job capped ..." (worker process).
# Grammar constraints (AWS-verified via throwaway filters): patterns support
# && but not ||, and wildcards sit inside the quoted value — so the two
# phrases are separate filters emitting into one metric; the alarm counts
# both.
resource "aws_cloudwatch_log_metric_filter" "job_failed" {
  name           = "${var.project}-${var.environment}-job-failed"
  log_group_name = aws_cloudwatch_log_group.task["worker"].name
  pattern        = "{ $.message = \"*job failed*\" }"

  metric_transformation {
    name          = "JobFailures"
    namespace     = local.metric_namespace
    value         = "1"
    default_value = "0"
  }
}

resource "aws_cloudwatch_log_metric_filter" "job_capped" {
  name           = "${var.project}-${var.environment}-job-capped"
  log_group_name = aws_cloudwatch_log_group.task["worker"].name
  pattern        = "{ $.message = \"*job capped*\" }"

  metric_transformation {
    name          = "JobFailures"
    namespace     = local.metric_namespace
    value         = "1"
    default_value = "0"
  }
}

# Unexpected API-level errors (domain failures are handled and logged as
# INFO/WARNING; ERROR here means something the error mapper did not plan for).
resource "aws_cloudwatch_log_metric_filter" "api_errors" {
  name           = "${var.project}-${var.environment}-api-errors"
  log_group_name = aws_cloudwatch_log_group.task["api"].name
  pattern        = "{ $.level = \"ERROR\" }"

  metric_transformation {
    name          = "ApiErrors"
    namespace     = local.metric_namespace
    value         = "1"
    default_value = "0"
  }
}

resource "aws_cloudwatch_log_metric_filter" "worker_errors" {
  name           = "${var.project}-${var.environment}-worker-errors"
  log_group_name = aws_cloudwatch_log_group.task["worker"].name
  pattern        = "{ $.level = \"ERROR\" }"

  metric_transformation {
    name          = "WorkerErrors"
    namespace     = local.metric_namespace
    value         = "1"
    default_value = "0"
  }
}

# --- Alarms -------------------------------------------------------------------

resource "aws_cloudwatch_metric_alarm" "job_failures" {
  alarm_name          = "${var.project}-${var.environment}-job-failures"
  alarm_description   = "A background job failed or hit the attempt cap; check the worker log stream for the reason."
  namespace           = local.metric_namespace
  metric_name         = "JobFailures"
  statistic           = "Sum"
  period              = 60
  evaluation_periods  = 5
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  # Idle-at-zero means long gaps with no data; that is health, not a problem.
  treat_missing_data = "notBreaching"
  alarm_actions      = [aws_sns_topic.alerts.arn]
  ok_actions         = [aws_sns_topic.alerts.arn]
  tags               = { Environment = var.environment }
}

resource "aws_cloudwatch_metric_alarm" "api_errors" {
  alarm_name          = "${var.project}-${var.environment}-api-errors"
  alarm_description   = "Unhandled API errors at elevated rate."
  namespace           = local.metric_namespace
  metric_name         = "ApiErrors"
  statistic           = "Sum"
  period              = 60
  evaluation_periods  = 10
  threshold           = 5
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
  ok_actions          = [aws_sns_topic.alerts.arn]
  tags                = { Environment = var.environment }
}

resource "aws_cloudwatch_metric_alarm" "worker_errors" {
  alarm_name          = "${var.project}-${var.environment}-worker-errors"
  alarm_description   = "ERROR-level logs from the worker process: something the job-failure handling did not plan for (a job failure itself fires the job-failures alarm)."
  namespace           = local.metric_namespace
  metric_name         = "WorkerErrors"
  statistic           = "Sum"
  period              = 60
  evaluation_periods  = 15
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
  ok_actions          = [aws_sns_topic.alerts.arn]
  tags                = { Environment = var.environment }
}
