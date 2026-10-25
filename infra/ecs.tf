resource "aws_ecs_cluster" "this" {
  name = "${var.project_name}-cluster"
}

resource "aws_cloudwatch_log_group" "render" {
  name              = "/ecs/${var.project_name}-render"
  retention_in_days = 14
}

resource "aws_security_group" "task" {
  name        = "${var.project_name}-task"
  description = "Outbound-only SG for the render Fargate task"
  vpc_id      = data.aws_vpc.default.id

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_ecs_task_definition" "render" {
  family                   = "${var.project_name}-render"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = "1024"
  memory                   = "3072"
  execution_role_arn       = aws_iam_role.task_execution.arn
  task_role_arn            = aws_iam_role.task.arn

  container_definitions = jsonencode([
    {
      name      = "render"
      image     = "${aws_ecr_repository.render.repository_url}:${var.container_image_tag}"
      essential = true
      environment = [
        { name = "OUTPUT_BUCKET", value = aws_s3_bucket.output.bucket },
        { name = "QUEUE_TABLE", value = aws_dynamodb_table.queue.name },
        { name = "UPLOAD_POST_PROFILE", value = var.upload_post_profile },
        { name = "GITHUB_REPO", value = var.github_repo },
        { name = "SNS_ALERT_TOPIC_ARN", value = aws_sns_topic.alerts.arn },
        { name = "AWS_REGION", value = var.aws_region },
        { name = "SITE_BUCKET", value = var.site_bucket },
      ]
      secrets = [
        { name = "UPLOAD_API_KEY", valueFrom = aws_secretsmanager_secret.upload_api_key.arn },
        { name = "GITHUB_TOKEN", valueFrom = aws_secretsmanager_secret.github_token.arn },
        { name = "FAL_API_KEY", valueFrom = aws_secretsmanager_secret.fal_api_key.arn },
      ]
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.render.name
          "awslogs-region"        = var.aws_region
          "awslogs-stream-prefix" = "render"
        }
      }
    }
  ])
}
