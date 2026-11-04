# Searched documents (text not included in the public repo)

In our deployment this folder holds each ASPPH document split into sections (one Markdown file per section)
plus a `.metadata.json` beside each one, which Bedrock Knowledge Bases reads for filtering and citations.

The section text is ASPPH's published material, so we don't republish it here; only the metadata files are kept,
so you can see how the index is organized. The original PDFs are public in ASPPH's challenge repo:
https://github.com/12turnbullb/us-breaking-barriers-2026/tree/main/ASPPH . To rebuild this folder from them,
put them under `data/reference/` and run `scripts/prepare_kb.py`, then `scripts/upload_kb.py`.
