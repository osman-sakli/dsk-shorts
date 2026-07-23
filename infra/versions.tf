terraform {
  required_version = ">= 1.5"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.4"
    }
  }
  # Local state for now — fine for a single-operator project. Move to an S3
  # backend (with its own small bucket) if this ever needs a second operator
  # or CI-driven applies.
}

provider "aws" {
  region = var.aws_region
}
