# Scripts

Command-line tools for setup and testing.

| File | What it does | Owner | Status |
|---|---|---|---|
| `prepare_kb.py` | PDFs → one Markdown file per section + metadata, with a word-for-word fidelity check; never overwrites hand edits | Gavin | **ready, run** |
| `check_ceph.py` | Checks the CEPH checklist against the PDF: 22 ids, domains, every word found | Gavin | **ready, run** |
| `create_kb.py` | Creates the bucket, vector index, IAM role, knowledge base and data source; safe to rerun | Gavin | **ran: KB `C4GJF8AJ7U`** |
| `upload_kb.py` | Uploads `kb/` + original PDFs to S3, starts the Bedrock sync, waits; refuses unreviewed sections | Gavin | **ran: 38/38 indexed** |
| `test_retrieval.py` | Runs the 16 retrieval tests against the live knowledge base | Gavin | **ran: 16/16 pass** |
| `add_source.py` | Adds one new document end to end (the CLI form of the intake pipeline) | Gavin | placeholder |
| `seed_users.py` | Creates the demo Cognito users and groups | software engineering | placeholder |
| `seed_schools.py` | Loads the school + default AI policies into DynamoDB | software engineering | placeholder |
| `smoke_test.sh` | Calls a running backend end to end (works with the mock agent) | software engineering | `/health` only |

`prepare_kb.py` and `check_ceph.py` need `pdftotext` (`brew install poppler`). The AWS scripts need `boto3` and the sandbox credentials.
