#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${1:-http://127.0.0.1:5000}"

curl -sS "$BASE_URL/api/health"
printf "\n"
curl -sS "$BASE_URL/api/config/summary"
printf "\n"
curl -sS -X POST "$BASE_URL/api/task1/execute" -H "Content-Type: application/json" -d '{}'
printf "\n"
curl -sS -X POST "$BASE_URL/api/task2/execute" -H "Content-Type: application/json" -d '{}'
printf "\n"
curl -sS -X POST "$BASE_URL/api/task3/execute" -H "Content-Type: application/json" -d '{}'
printf "\n"
