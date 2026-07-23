# LinkedIn posting — rotates through content/linkedin-posts.json every ~48h,
# posting AS the Digital Safety Knights company page. upload-post.com has a
# single LinkedIn OAuth connection (the owner's); the personal/company
# distinction happens at post time via target_linkedin_page_id, not via a
# separate "connect as page" flow.
locals {
  linkedin_page_urn = "urn:li:organization:133458013" # Digital Safety Knights
}

data "archive_file" "linkedin_lambda" {
  type        = "zip"
  output_path = "${path.module}/.build/linkedin_post.zip"
  source_dir  = "${path.module}/../pipeline/linkedin_lambda"
}

resource "aws_iam_role" "linkedin_lambda" {
  name = "${var.project_name}-linkedin-lambda"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "linkedin_lambda_logs" {
  role       = aws_iam_role.linkedin_lambda.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy" "linkedin_lambda_permissions" {
  name = "linkedin-lambda-permissions"
  role = aws_iam_role.linkedin_lambda.id
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
      }
    ]
  })
}

resource "aws_lambda_function" "linkedin_post" {
  function_name    = "${var.project_name}-linkedin-post"
  role             = aws_iam_role.linkedin_lambda.arn
  handler          = "linkedin_post.handler"
  runtime          = "python3.12"
  timeout          = 30
  filename         = data.archive_file.linkedin_lambda.output_path
  source_code_hash = data.archive_file.linkedin_lambda.output_base64sha256
  # Reuses the account's existing published layer (built from the same
  # requests/certifi/charset_normalizer/idna/urllib3 bundle as the site's
  # Stripe Lambdas) instead of publishing a near-duplicate layer.
  layers = ["arn:aws:lambda:us-east-1:339712706640:layer:stripe-python:1"]

  environment {
    variables = {
      QUEUE_TABLE               = aws_dynamodb_table.queue.name
      UPLOAD_API_KEY_SECRET_ARN = aws_secretsmanager_secret.upload_api_key.arn
      UPLOAD_POST_PROFILE       = var.upload_post_profile
      LINKEDIN_PAGE_URN         = local.linkedin_page_urn
    }
  }
}

# Same caveat as the Discord rule: rate(2 days) drifts from a fixed wall-clock
# time since it's relative to when this rule was enabled, not calendar-aligned.
resource "aws_cloudwatch_event_rule" "linkedin_post" {
  name                = "${var.project_name}-linkedin-post"
  schedule_expression = "rate(2 days)"
}

resource "aws_cloudwatch_event_target" "linkedin_post" {
  rule = aws_cloudwatch_event_rule.linkedin_post.name
  arn  = aws_lambda_function.linkedin_post.arn
}

resource "aws_lambda_permission" "linkedin_post_eventbridge" {
  statement_id  = "AllowEventBridge"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.linkedin_post.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.linkedin_post.arn
}

output "linkedin_lambda_name" {
  value = aws_lambda_function.linkedin_post.function_name
}
