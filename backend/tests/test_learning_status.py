"""Lab Models panel data for the read-only learned models."""

from __future__ import annotations

import json

from learning.config import other_models_status


def test_reports_every_model_as_unavailable_and_off_when_nothing_is_trained(tmp_path):
    rows = other_models_status({"MILO_ARTIFACTS_DIR": str(tmp_path)})
    assert [r["name"] for r in rows] == [
        "fast_detector",
        "memory_embedder",
        "instruction_parser",
        "world_model",
    ]
    assert all(
        not r["available"] and not r["enabled"] and r["headline"] is None for r in rows
    )


def test_reads_headline_numbers_and_flags(tmp_path):
    (tmp_path / "parser").mkdir()
    (tmp_path / "parser" / "parser.pkl").write_bytes(b"x")
    (tmp_path / "parser" / "eval.json").write_text(
        json.dumps(
            {
                "learned_alone": {"exact_accuracy": 0.62},
                "rules": {"exact_accuracy": 0.137},
            }
        )
    )
    (tmp_path / "memory_embedder").mkdir()
    (tmp_path / "memory_embedder" / "eval.json").write_text(
        "not json"
    )  # unreadable -> no headline
    env = {
        "MILO_ARTIFACTS_DIR": str(tmp_path),
        "MILO_LEARNED_PARSER": "1",
        "MEMORY_EMBEDDING_PROVIDER": "learned",
        "MILO_WORLD_MODEL": "1",  # without MILO_PLAN_RANKING it is not really on
    }
    rows = {r["name"]: r for r in other_models_status(env)}
    assert (
        rows["instruction_parser"]["available"]
        and rows["instruction_parser"]["enabled"]
    )
    assert "0.62 exact vs 0.14" in rows["instruction_parser"]["headline"]
    assert (
        rows["memory_embedder"]["enabled"]
        and rows["memory_embedder"]["headline"] is None
    )
    assert rows["world_model"]["enabled"] is False
