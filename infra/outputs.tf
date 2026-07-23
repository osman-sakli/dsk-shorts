output "ecr_repository_url" {
  value = aws_ecr_repository.render.repository_url
}

output "s3_output_bucket" {
  value = aws_s3_bucket.output.bucket
}

output "dynamodb_queue_table" {
  value = aws_dynamodb_table.queue.name
}

output "ecs_cluster_name" {
  value = aws_ecs_cluster.this.name
}

output "sns_alert_topic_arn" {
  value = aws_sns_topic.alerts.arn
}
