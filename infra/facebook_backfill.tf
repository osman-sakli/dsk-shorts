# One-time backfill: posts the 6 AI-path videos (ai-001..ai-006) already
# live on TikTok/Instagram/YouTube to Facebook too, one every 4 hours, since
# they predate Facebook being connected on upload-post.com (2026-08-01).
# TEAR DOWN once facebook_backfill.py's BACKFILL_ITEMS list is exhausted —
# delete this file and run `terraform apply` again. Ongoing daily posts
# already include Facebook via the main render task (see AUTO_PLATFORMS in
# pipeline/entrypoint.py) — this is only for the pre-existing backlog.

data "archive_file" "facebook_backfill_lambda" {
  type        = "zip"
  output_path = "${path.module}/.build/facebook_backfill.zip"
  source_dir  = "${path.module}/../pipeline/facebook_backfill_lambda"
}

resource "aws_iam_role" "facebook_backfill_lambda" {
  name = "${var.project_name}-facebook-backfill-lambda"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "facebook_backfill_lambda_logs" {
  role       = aws_iam_role.facebook_backfill_lambda.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy" "facebook_backfill_lambda_permissions" {
  name = "facebook-backfill-lambda-permissions"
  role = aws_iam_role.facebook_backfill_lambda.id
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
        Resource = [aws_secretsmanager_secret.upload_api_key.arn]
      },
      {
        Effect   = "Allow"
        Action   = ["s3:GetObject"]
        Resource = ["${aws_s3_bucket.output.arn}/*"]
      }
    ]
  })
}

resource "aws_lambda_function" "facebook_backfill" {
  function_name    = "${var.project_name}-facebook-backfill"
  role             = aws_iam_role.facebook_backfill_lambda.arn
  handler          = "facebook_backfill.handler"
  runtime          = "python3.12"
  timeout          = 180
  memory_size      = 512
  filename         = data.archive_file.facebook_backfill_lambda.output_path
  source_code_hash = data.archive_file.facebook_backfill_lambda.output_base64sha256
  # Same shared requests/certifi layer the linkedin lambda reuses.
  layers = ["arn:aws:lambda:us-east-1:339712706640:layer:stripe-python:1"]

  environment {
    variables = {
      QUEUE_TABLE               = aws_dynamodb_table.queue.name
      OUTPUT_BUCKET             = aws_s3_bucket.output.bucket
      UPLOAD_API_KEY_SECRET_ARN = aws_secretsmanager_secret.upload_api_key.arn
      UPLOAD_POST_PROFILE       = var.upload_post_profile
    }
  }
}

resource "aws_cloudwatch_event_rule" "facebook_backfill" {
  name                = "${var.project_name}-facebook-backfill"
  schedule_expression = "rate(4 hours)"
}

resource "aws_cloudwatch_event_target" "facebook_backfill" {
  rule = aws_cloudwatch_event_rule.facebook_backfill.name
  arn  = aws_lambda_function.facebook_backfill.arn
}

resource "aws_lambda_permission" "facebook_backfill_eventbridge" {
  statement_id  = "AllowEventBridge"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.facebook_backfill.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.facebook_backfill.arn
}

output "facebook_backfill_lambda_name" {
  value = aws_lambda_function.facebook_backfill.function_name
}
