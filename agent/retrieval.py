"""Station 3: Find sources. Searches the Bedrock knowledge base and numbers the passages P1, P2…

Code, not Claude, decides what to search for and which sources are allowed:
  guidance  = evidence for AI recommendations (ASPPH AI Framework…)
  workforce = evidence for workforce expectations (Competency Mapping…)
  exemplar  = never used as evidence (excluded here)
The snippet is the exact chunk text. Nobody paraphrases it.
"""

import json
import os
from pathlib import Path

import boto3

from phact_contracts.agent import Passage

ROOT = Path(__file__).resolve().parents[1]
_ids_file = ROOT / "knowledge-base" / "kb_ids.json"
_ids = json.loads(_ids_file.read_text()) if _ids_file.exists() else {}
KB_ID = os.getenv("KB_ID", _ids.get("kb_id", ""))
BUCKET = os.getenv("KNOWLEDGE_BUCKET", _ids.get("knowledge_bucket", ""))
MIN_SCORE = float(os.getenv("RETRIEVAL_MIN_SCORE", "0.4"))

_rt = None


def _client():
    global _rt
    if _rt is None:
        _rt = boto3.client("bedrock-agent-runtime", region_name=os.getenv("AWS_REGION", "us-west-2"))
    return _rt


STATUS_ACTIVE = {"equals": {"key": "status", "value": "active"}}
STATUS_SECONDARY = {"equals": {"key": "status", "value": "secondary"}}


def search(query: str, source_types: list[str], k: int = 4, extra: list[dict] | None = None,
           status: dict | None = STATUS_ACTIVE) -> list[dict]:
    """One KB search. Returns raw hits: text, score, metadata. `extra` adds metadata filters (andAll),
    e.g. [{"equals": {"key": "material_type", "value": "homework"}}] for the practice pattern cards."""
    flt = ({"equals": {"key": "source_type", "value": source_types[0]}} if len(source_types) == 1
           else {"in": {"key": "source_type", "value": source_types}})
    # Lifecycle (ASPPH admin): by default only ACTIVE documents; retired ones are never searched, and an
    # older edition ("secondary") only as a labelled fallback (see PassageStack.add).
    extra = [*(extra or []), *([status] if status else [])]
    if extra:
        flt = {"andAll": [flt, *extra]}
    res = _client().retrieve(
        knowledgeBaseId=KB_ID, retrievalQuery={"text": query},
        retrievalConfiguration={"vectorSearchConfiguration": {"numberOfResults": k, "filter": flt}})
    hits = []
    for r in res["retrievalResults"]:
        md = r.get("metadata", {})
        hits.append({"text": r["content"]["text"], "score": float(r.get("score", 0)),
                     "doc_id": md.get("doc_id", ""), "title": md.get("title", ""), "section": md.get("section"),
                     "source_type": md.get("source_type", "guidance"), "original": md.get("original", ""),
                     "aias_level": md.get("aias_level"), "material_type": md.get("material_type"),
                     "status": md.get("status", "active")})
    return hits


class PassageStack:
    """Collects passages across several searches, drops weak and duplicate ones, numbers them P1…Pn."""

    def __init__(self, start: int = 1, existing: list[Passage] | None = None):
        self.passages: list[Passage] = list(existing or [])
        self._next = start
        self._seen = {p.snippet[:200] for p in self.passages}
        self.queries: list[dict] = []          # for the playground's "what did it search for" view

    @staticmethod
    def _fetch(query: str, source_types: list[str], k: int = 4, extra: list[dict] | None = None) -> list[dict]:
        hits = search(query, source_types, k, extra)
        if not any(h["score"] >= MIN_SCORE for h in hits):  # nothing current: try an older edition, labelled
            hits = search(query, source_types, k, extra, status=STATUS_SECONDARY)
            for h in hits:
                h["title"] = f"{h['title']} (older edition)"
        return hits

    def add(self, query: str, source_types: list[str], k: int = 4, why: str = "",
            extra: list[dict] | None = None) -> list[str]:
        return self._take(query, source_types, why, extra, self._fetch(query, source_types, k, extra))

    def add_many(self, specs: list[dict]) -> list[list[str]]:
        """Several searches at once: the KB calls run in parallel (each is a network round trip), then the
        results are numbered and de-duplicated in the order given, so P1…Pn are exactly what one-by-one
        `add` calls would produce. specs: [{"query", "source_types", "k", "why", "extra"}]."""
        from concurrent.futures import ThreadPoolExecutor
        if not specs:
            return []
        with ThreadPoolExecutor(max_workers=min(8, len(specs))) as pool:
            fetched = list(pool.map(lambda s: self._fetch(s["query"], s["source_types"], s.get("k", 4), s.get("extra")), specs))
        return [self._take(s["query"], s["source_types"], s.get("why", ""), s.get("extra"), hits) for s, hits in zip(specs, fetched)]

    def _take(self, query: str, source_types: list[str], why: str, extra: list[dict] | None, hits: list[dict]) -> list[str]:
        ids = []
        for h in hits:
            if h["score"] < MIN_SCORE:
                continue
            key = h["text"][:200]
            if key in self._seen:
                ids.extend(p.id for p in self.passages if p.snippet[:200] == key)
                continue
            self._seen.add(key)
            pid = f"P{self._next}"
            self._next += 1
            self.passages.append(Passage(
                id=pid, title=h["title"], section=h["section"], snippet=h["text"],
                # pattern cards cite a web page; ASPPH documents cite our stored PDF
                uri=(h["original"] if h["original"].startswith("http") else f"s3://{BUCKET}/{h['original']}") if h["original"] else "",
                source_type=h["source_type"] if h["source_type"] in ("guidance", "workforce", "exemplar", "practice") else "guidance"))
            ids.append(pid)
        self.queries.append({"query": query, "filter": source_types + [f"{list(e.values())[0]['key']}" for e in extra or []], "why": why, "kept": ids,
                             "scores": [round(h["score"], 2) for h in hits]})
        return ids


def presigned_source_link(uri: str, expires: int = 300) -> str:
    """Turn s3://bucket/originals/doc.pdf#page=7 into a 5-minute link that opens that page."""
    if not uri.startswith("s3://"):
        return ""
    path, _, frag = uri[5:].partition("#")
    bucket, _, key = path.partition("/")
    from botocore.config import Config
    s3 = boto3.client("s3", region_name=os.getenv("AWS_REGION", "us-west-2"),
                      config=Config(signature_version="s3v4"))  # required for KMS-encrypted buckets
    url = s3.generate_presigned_url("get_object", Params={"Bucket": bucket, "Key": key}, ExpiresIn=expires)
    return url + (f"#{frag}" if frag else "")


def peer_examples(query: str, k: int = 2) -> list[dict]:
    """Approved example syllabi shared by professors (ASPPH-reviewed). For INSPIRATION only: they're returned
    separately from the PassageStack, so they can never be cited as evidence (a peer syllabus isn't an ASPPH finding)."""
    try:
        hits = search(query, ["exemplar"], k)
    except Exception:  # noqa: BLE001  (no exemplars yet, or the filter isn't indexed: analysis goes on without them)
        return []
    return [{"title": h["title"], "section": h["section"], "text": h["text"][:1500], "score": round(h["score"], 2)}
            for h in hits if h["score"] >= MIN_SCORE]


def example_blocks(examples: list[dict]) -> str:
    if not examples:
        return ""
    return ("\n\n" + "\n".join(f'<peer_example title="{e["title"]}" section="{e["section"] or ""}">\n{e["text"]}\n</peer_example>'
                                 for e in examples)
            + "\n<peer_example_rule>Peer examples are approved syllabi from other faculty, shared with consent. Use them for "
              "inspiration on concrete wording and design. Never cite them: evidence_ids may only name <passage> ids.</peer_example_rule>")
