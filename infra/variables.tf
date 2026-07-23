variable "aws_region" {
  default = "us-east-1"
}

variable "project_name" {
  default = "dsk-shorts"
}

variable "alert_email" {
  description = "Where render/publish failure alerts are sent (SNS email subscription)."
  type        = string
  default     = "osmansakli@yahoo.com"
}

variable "github_repo" {
  description = "owner/repo used for the 'need new scripts' fallback issue."
  type        = string
  default     = "osman-sakli/dsk-shorts"
}

variable "upload_post_profile" {
  description = "upload-post.com managed-user profile name to publish as."
  type        = string
  default     = "DSK"
}

variable "container_image_tag" {
  default = "latest"
}

variable "output_retention_days" {
  description = "How long rendered mp4/thumbnail/caption objects live in S3 before expiring."
  type        = number
  default     = 90
}

# Secrets — never hardcode these. Pass at apply time, e.g.:
#   TF_VAR_upload_api_key=... TF_VAR_github_token=... terraform apply
variable "upload_api_key" {
  description = "upload-post.com API key."
  type        = string
  sensitive   = true
}

variable "github_token" {
  description = "GitHub token (repo scope) used only to open 'need new scripts' issues."
  type        = string
  sensitive   = true
}

variable "discord_webhook_url" {
  description = "Discord webhook URL for the DSK server's announcements channel. Leave empty to skip creating the Discord posting Lambda entirely."
  type        = string
  sensitive   = true
  default     = ""
}
