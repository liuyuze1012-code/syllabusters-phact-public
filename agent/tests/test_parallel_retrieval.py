"""add_many runs KB searches in parallel but must number and de-duplicate exactly like one-by-one add()."""

import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import retrieval  # noqa: E402


def fake_search(query, source_types, k=4, extra=None, status=None):
    time.sleep(random.uniform(0, 0.05))  # finish in random order, like real network calls
    base = sum(map(ord, query)) % 5
    # overlapping texts across queries, so de-duplication matters; one weak hit, filtered out
    return [{"text": f"passage {(base + i) % 6} " + "x" * 210, "score": 0.9 if i < 2 else 0.1, "title": f"T{(base + i) % 6}",
             "section": "s", "original": "doc.pdf", "source_type": "guidance", "status": "active"} for i in range(k)]


SPECS = [{"query": q, "source_types": ["guidance"], "k": 3, "why": q} for q in
         ["ai policy", "ai reflection", "simulations", "ceph 2 teaching", "ceph 2 workforce", "ceph 7 teaching", "ceph 7 workforce"]]


def test_add_many_matches_sequential(monkeypatch):
    monkeypatch.setattr(retrieval, "search", fake_search)
    one = retrieval.PassageStack()
    seq = [one.add(s["query"], s["source_types"], s["k"], s["why"]) for s in SPECS]
    two = retrieval.PassageStack()
    par = two.add_many(SPECS)
    assert par == seq
    assert [(p.id, p.snippet) for p in two.passages] == [(p.id, p.snippet) for p in one.passages]
    assert [q["kept"] for q in two.queries] == [q["kept"] for q in one.queries]


def test_add_many_is_parallel(monkeypatch):
    monkeypatch.setattr(retrieval, "search", lambda *a, **k: (time.sleep(0.2), [])[1])
    t = time.monotonic()
    retrieval.PassageStack().add_many(SPECS)  # 7 searches (+7 fallbacks) of 0.2 s each: ~2.8 s one by one
    assert time.monotonic() - t < 1.2
