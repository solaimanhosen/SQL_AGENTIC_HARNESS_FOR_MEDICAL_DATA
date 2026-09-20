"""Append one record per question to a log file, as JSON Lines.

The log is what makes a run reviewable after the fact. It holds the question, the answer,
the SQL that actually ran and what it cost, which is also the raw material the evaluation
harness in Step 6 will score.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .agent import AgentResult


def build_record(result: "AgentResult") -> dict:
    """The full run as plain data, safe to serialise and to diff."""
    structured = result.structured
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "question": result.question,
        "answer": result.answer,
        "headline": structured.headline if structured else None,
        "findings": (
            [{"statement": f.statement, "query_numbers": f.query_numbers} for f in structured.findings]
            if structured
            else []
        ),
        "definitions_used": list(structured.definitions_used) if structured else [],
        "time_window": (
            {"months": structured.time_window.months, "description": structured.time_window.description}
            if structured
            else None
        ),
        "assumptions": list(structured.assumptions) if structured else [],
        "caveats": list(structured.caveats) if structured else [],
        "queries": [asdict(record) for record in result.queries],
        "issues": asdict(result.issues),
        "as_of": str(result.as_of),
        "model": result.model,
        "elapsed_s": round(result.elapsed_s, 2),
        "input_tokens": result.input_tokens,
        "output_tokens": result.output_tokens,
    }


def log_run(result: "AgentResult", path: Path) -> Path:
    """Append one run to the log, creating the folder if needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(build_record(result), ensure_ascii=False) + "\n")
    return path
