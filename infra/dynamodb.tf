# Single table: day-index state (pk="STATE") + one item per publish attempt
# (pk="DAY#<NN>#<date>"). On-demand billing — traffic is ~1-2 writes/day.
resource "aws_dynamodb_table" "queue" {
  name         = "${var.project_name}-publish-queue"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "pk"

  attribute {
    name = "pk"
    type = "S"
  }
}
