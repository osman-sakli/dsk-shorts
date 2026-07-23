# NOTE: EventBridge cron is UTC and does not observe DST. 16:00 UTC = 12:00pm
# America/New_York during EDT (roughly mid-March to early-November). During
# EST (winter) this task will run at 11:00am ET instead of noon. Fine for a
# "once a day" content pipeline; revisit if exact wall-clock time matters.
resource "aws_cloudwatch_event_rule" "daily_render" {
  name                = "${var.project_name}-daily-render"
  schedule_expression = "cron(0 16 * * ? *)"
}

resource "aws_cloudwatch_event_target" "daily_render" {
  rule     = aws_cloudwatch_event_rule.daily_render.name
  arn      = aws_ecs_cluster.this.arn
  role_arn = aws_iam_role.eventbridge_ecs.arn

  ecs_target {
    task_definition_arn = aws_ecs_task_definition.render.arn
    launch_type         = "FARGATE"
    network_configuration {
      subnets          = data.aws_subnets.default.ids
      security_groups  = [aws_security_group.task.id]
      assign_public_ip = true # avoids a NAT gateway (~$32/mo) for outbound-only traffic
    }
  }
}
