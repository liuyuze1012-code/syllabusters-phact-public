"""The placeholder agent answers both modes with contract-valid output."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from phact_contracts import FIXTURES
from phact_contracts.agent import AnalyzeResponse, ReviseResponse

from main import handle


def test_analyze_mock():
    req = json.loads((FIXTURES / "analyze_request.json").read_text())
    req["job_id"] = "abc"
    out = AnalyzeResponse.model_validate(handle(req))
    assert out.job_id == "abc"


def test_revise_mock():
    analyze = json.loads((FIXTURES / "analyze_response.json").read_text())
    req = {"mode": "revise", "job_id": "r1", "analysis_id": "a1", "message": "make it simpler",
           "target_edit_ids": ["E2"], "outline": analyze["outline"], "edits": analyze["edits"],
           "passages": analyze["passages"]}
    assert ReviseResponse.model_validate(handle(req)).edits[0].version == 2


def test_unknown_mode():
    assert handle({"mode": "nope", "job_id": "x"})["ok"] is False


def _revise(message: str) -> dict:
    analyze = json.loads((FIXTURES / "analyze_response.json").read_text())
    return {"mode": "revise", "job_id": "r2", "analysis_id": "a1", "message": message, "scope": "all",
            "outline": analyze["outline"], "edits": analyze["edits"], "passages": analyze["passages"]}


def test_chat_kinds():
    assert ReviseResponse.model_validate(handle(_revise("Why did you suggest E2?"))).kind == "question"
    added = ReviseResponse.model_validate(handle(_revise("Add something on data ethics")))
    assert added.kind == "add" and added.new_passages[0].id == "P4"
    assert ReviseResponse.model_validate(handle(_revise("less AI overall"))).kind == "change"


def test_question_cannot_change_edits():
    import pytest
    bad = json.loads((FIXTURES / "revise_response.json").read_text())
    bad["kind"] = "question"
    with pytest.raises(Exception):
        ReviseResponse.model_validate(bad)
