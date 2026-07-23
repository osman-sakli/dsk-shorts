# Reuses the GitHub Actions OIDC provider already present in this account
# (set up for an earlier project) instead of creating a second one.
data "aws_iam_openid_connect_provider" "github" {
  url = "https://token.actions.githubusercontent.com"
}

resource "aws_iam_role" "github_actions_ecr_push" {
  name = "${var.project_name}-github-actions-ecr-push"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Federated = data.aws_iam_openid_connect_provider.github.arn }
      Action    = "sts:AssumeRoleWithWebIdentity"
      # AWS requires the trust policy to scope on "sub" (or job_workflow_ref)
      # specifically — a repository/ref-only condition is rejected as
      # "not scoped". This account has immutable-ID subject claims enabled,
      # so sub looks like "repo:owner@123/repo@456:ref:...". The numeric IDs
      # are stable but we wildcard them (StringLike) rather than hardcode,
      # and pin the repository/ref claims as belt-and-suspenders.
      Condition = {
        StringEquals = {
          "token.actions.githubusercontent.com:aud"        = "sts.amazonaws.com"
          "token.actions.githubusercontent.com:repository" = var.github_repo
          "token.actions.githubusercontent.com:ref"        = "refs/heads/master"
        }
        StringLike = {
          "token.actions.githubusercontent.com:sub" = "repo:${split("/", var.github_repo)[0]}@*/${split("/", var.github_repo)[1]}@*:ref:refs/heads/master"
        }
      }
    }]
  })
}

resource "aws_iam_role_policy" "github_actions_ecr_push" {
  name = "ecr-push"
  role = aws_iam_role.github_actions_ecr_push.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["ecr:GetAuthorizationToken"]
        Resource = ["*"]
      },
      {
        Effect = "Allow"
        Action = [
          "ecr:BatchCheckLayerAvailability",
          "ecr:PutImage",
          "ecr:InitiateLayerUpload",
          "ecr:UploadLayerPart",
          "ecr:CompleteLayerUpload",
          "ecr:BatchGetImage",
        ]
        Resource = [aws_ecr_repository.render.arn]
      }
    ]
  })
}

output "github_actions_role_arn" {
  value = aws_iam_role.github_actions_ecr_push.arn
}
