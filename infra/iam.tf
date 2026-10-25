# --- Task execution role: pulls the image from ECR, writes logs, reads secrets ---
resource "aws_iam_role" "task_execution" {
  name = "${var.project_name}-task-execution"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ecs-tasks.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "task_execution_managed" {
  role       = aws_iam_role.task_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_iam_role_policy" "task_execution_secrets" {
  name = "read-secrets"
  role = aws_iam_role.task_execution.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = ["secretsmanager:GetSecretValue"]
      Resource = [
        aws_secretsmanager_secret.upload_api_key.arn,
        aws_secretsmanager_secret.github_token.arn,
        aws_secretsmanager_secret.fal_api_key.arn,
      ]
    }]
  })
}

# --- Task role: the app's own runtime AWS permissions ---
resource "aws_iam_role" "task" {
  name = "${var.project_name}-task"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ecs-tasks.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "task_permissions" {
  name = "render-task-permissions"
  role = aws_iam_role.task.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["s3:PutObject", "s3:GetObject"]
        Resource = ["${aws_s3_bucket.output.arn}/*"]
      },
      {
        # find_existing_render() lists the output bucket to check whether a
        # script_id already has a render before paying fal.ai again — this
        # was missing when that check was added, so every run silently hit
        # AccessDenied, logged a warning, and fell through to "generate"
        # regardless. That defeated the entire point of the check.
        Effect   = "Allow"
        Action   = ["s3:ListBucket"]
        Resource = [aws_s3_bucket.output.arn]
      },
      {
        Effect   = "Allow"
        Action   = ["dynamodb:GetItem", "dynamodb:PutItem"]
        Resource = [aws_dynamodb_table.queue.arn]
      },
      {
        # publish_to_site_library() copies each render's mp4+thumbnail onto
        # the public website bucket under shorts/, for frontend/topics.html.
        # Narrow on purpose: write-only, and only that one prefix — this
        # task has no business touching anything else on digitalsafetyknights.org.
        Effect   = "Allow"
        Action   = ["s3:PutObject"]
        Resource = ["arn:aws:s3:::${var.site_bucket}/shorts/*"]
      },
      {
        Effect   = "Allow"
        Action   = ["polly:SynthesizeSpeech"]
        Resource = ["*"]
      },
      {
        Effect   = "Allow"
        Action   = ["sns:Publish"]
        Resource = [aws_sns_topic.alerts.arn]
      }
    ]
  })
}

# --- Role EventBridge assumes to launch the Fargate task ---
resource "aws_iam_role" "eventbridge_ecs" {
  name = "${var.project_name}-eventbridge-ecs"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "events.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "eventbridge_run_task" {
  name = "run-render-task"
  role = aws_iam_role.eventbridge_ecs.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["ecs:RunTask"]
        Resource = [replace(aws_ecs_task_definition.render.arn, "/:\\d+$/", ":*")]
      },
      {
        Effect   = "Allow"
        Action   = ["iam:PassRole"]
        Resource = [aws_iam_role.task_execution.arn, aws_iam_role.task.arn]
      }
    ]
  })
}
