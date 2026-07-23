# Secrets live only in Secrets Manager, injected into the container as env
# vars by ECS at task launch — never written to the image, repo, or state
# beyond this resource (state file itself should be treated as sensitive).

resource "aws_secretsmanager_secret" "upload_api_key" {
  name = "${var.project_name}/upload-api-key"
}

resource "aws_secretsmanager_secret_version" "upload_api_key" {
  secret_id     = aws_secretsmanager_secret.upload_api_key.id
  secret_string = var.upload_api_key
}

resource "aws_secretsmanager_secret" "github_token" {
  name = "${var.project_name}/github-token"
}

resource "aws_secretsmanager_secret_version" "github_token" {
  secret_id     = aws_secretsmanager_secret.github_token.id
  secret_string = var.github_token
}
