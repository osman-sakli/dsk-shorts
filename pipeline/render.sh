#!/usr/bin/env bash
# Usage: bash pipeline/render.sh 001-knight-rule-1
set -euo pipefail
ID="${1:?usage: render.sh <script-id>}"
npx remotion render "src/index.ts" "$ID" "out/$ID.mp4" --codec h264
echo "Rendered out/$ID.mp4"
