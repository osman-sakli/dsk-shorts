resource "aws_ecr_repository" "render" {
  name                 = var.project_name
  image_tag_mutability = "MUTABLE"
}

# Keep storage bounded — only the last 5 images.
resource "aws_ecr_lifecycle_policy" "render" {
  repository = aws_ecr_repository.render.name
  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "keep last 5 images"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = 5
      }
      action = { type = "expire" }
    }]
  })
}
