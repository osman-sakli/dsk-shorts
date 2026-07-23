# Archival storage for rendered output — not public. upload-post.com receives
# the video by direct multipart upload from the task, not by fetching from S3.
resource "aws_s3_bucket" "output" {
  bucket = "${var.project_name}-out-${data.aws_caller_identity.current.account_id}"
}

resource "aws_s3_bucket_public_access_block" "output" {
  bucket                  = aws_s3_bucket.output.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_lifecycle_configuration" "output" {
  bucket = aws_s3_bucket.output.id
  rule {
    id     = "expire-old-renders"
    status = "Enabled"
    filter {}
    expiration {
      days = var.output_retention_days
    }
  }
}
