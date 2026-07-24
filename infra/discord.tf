# Every resource below is gated on discord_webhook_url being set — leave it
# empty (the default) to skip Discord entirely; nothing here gets created.
locals {
  discord_enabled = var.discord_webhook_url != ""
}

resource "aws_secretsmanager_secret" "discord_webhook" {
  count = local.discord_enabled ? 1 : 0
  name  = "${var.project_name}/discord-webhook-url"
}

resource "aws_secretsmanager_secret_version" "discord_webhook" {
  count         = local.discord_enabled ? 1 : 0
  secret_id     = aws_secretsmanager_secret.discord_webhook[0].id
  secret_string = var.discord_webhook_url
}

data "archive_file" "discord_lambda" {
  count       = local.discord_enabled ? 1 : 0
  type        = "zip"
  output_path = "${path.module}/.build/discord_post.zip"

  source {
    content  = file("${path.module}/../pipeline/discord_post.py")
    filename = "discord_post.py"
  }
  source {
    content  = file("${path.module}/../content/discord-posts.json")
    filename = "discord-posts.json"
  }
}

resource "aws_iam_role" "discord_lambda" {
  count = local.discord_enabled ? 1 : 0
  name  = "${var.project_name}-discord-lambda"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "discord_lambda_logs" {
  count      = local.discord_enabled ? 1 : 0
  role       = aws_iam_role.discord_lambda[0].name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy" "discord_lambda_permissions" {
  count = local.discord_enabled ? 1 : 0
  name  = "discord-lambda-permissions"
  role  = aws_iam_role.discord_lambda[0].id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["dynamodb:GetItem", "dynamodb:PutItem"]
        Resource = [aws_dynamodb_table.queue.arn]
      },
      {
        Effect   = "Allow"
        Action   = ["secretsmanager:GetSecretValue"]
        Resource = [aws_secretsmanager_secret.discord_webhook[0].arn]
      }
    ]
  })
}

resource "aws_lambda_function" "discord_post" {
  count            = local.discord_enabled ? 1 : 0
  function_name    = "${var.project_name}-discord-post"
  role             = aws_iam_role.discord_lambda[0].arn
  handler          = "discord_post.handler"
  runtime          = "python3.12"
  timeout          = 15
  filename         = data.archive_file.discord_lambda[0].output_path
  source_code_hash = data.archive_file.discord_lambda[0].output_base64sha256

  environment {
    variables = {
      QUEUE_TABLE                = aws_dynamodb_table.queue.name
      DISCORD_WEBHOOK_SECRET_ARN = aws_secretsmanager_secret.discord_webhook[0].arn
    }
  }
}

# Daily, fully automatic — no approval step. Fixed at 17:00 ET (21:00 UTC,
# EDT); like the other daily cron in this project, it'll land an hour off
# during EST (winter) since EventBridge cron doesn't observe DST.
resource "aws_cloudwatch_event_rule" "discord_post" {
  count               = local.discord_enabled ? 1 : 0
  name                = "${var.project_name}-discord-post"
  schedule_expression = "cron(0 21 * * ? *)"
}

resource "aws_cloudwatch_event_target" "discord_post" {
  count = local.discord_enabled ? 1 : 0
  rule  = aws_cloudwatch_event_rule.discord_post[0].name
  arn   = aws_lambda_function.discord_post[0].arn
}

resource "aws_lambda_permission" "discord_post_eventbridge" {
  count         = local.discord_enabled ? 1 : 0
  statement_id  = "AllowEventBridge"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.discord_post[0].function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.discord_post[0].arn
}
