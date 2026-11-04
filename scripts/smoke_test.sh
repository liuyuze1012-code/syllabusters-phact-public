#!/usr/bin/env bash
# End-to-end check against a running backend (local or deployed), with the mock agent.
# Usage: API=http://localhost:8000 ./smoke_test.sh
set -euo pipefail
API="${API:-http://localhost:8000}"
curl -fsS "$API/health" && echo
# TODO: create course → upload-url → PUT file → register syllabus → POST /api/jobs → poll until COMPLETE
