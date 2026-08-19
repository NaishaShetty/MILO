"""
test_api_planner.py

Purpose
-------
Verifies the Phase 4 Planning API (`api/routes/planner.py`) behaves as
a thin HTTP wrapper around `backend/planner/`: request validation,
delegation to `factory.create_planner`/`PlanValidator`/
`PlannerEvaluator`, and that the JSON returned matches the real
Pydantic models those components already produce (no hand-reconstructed
response shape). Uses FastAPI's `TestClient` directly against the real
`app` -- no simulator, no live LLM, no network access; every planner
these endpoints exercise by default (`rule_based`, `behavior_tree`, and
`react` with no configured LLM client, which falls back to
`rule_based`) is deterministic and network-free by construction.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from api.app import app

client = TestClient(app)

_STORE_TASK = {
    "task_type": "single",
    "goal": "store",
    "object": "apple",
    "target": "refrigerator",
}


def test_plan_endpoint_returns_valid_plan_for_store_goal():
    response = client.post(
        "/api/v1/planner/plan", json={"task": _STORE_TASK, "planner_type": "rule_based"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["planner_type"] == "rule_based"
    actions = [s["action"] for s in body["plan"]["steps"]]
    assert actions == [
        "locate",
        "navigate",
        "pickup",
        "locate",
        "navigate",
        "open",
        "place",
        "close",
    ]
    assert body["validation"]["valid"] is True


def test_plan_endpoint_defaults_to_rule_based():
    response = client.post("/api/v1/planner/plan", json={"task": _STORE_TASK})
    assert response.status_code == 200
    assert response.json()["planner_type"] == "rule_based"


def test_plan_endpoint_behavior_tree_strategy():
    response = client.post(
        "/api/v1/planner/plan",
        json={"task": _STORE_TASK, "planner_type": "behavior_tree"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert "behavior_tree" in body["plan"]["metadata"]


def test_plan_endpoint_react_without_llm_falls_back_to_rule_based():
    response = client.post(
        "/api/v1/planner/plan", json={"task": _STORE_TASK, "planner_type": "react"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["plan"]["metadata"]["react_fallback"] is True


def test_plan_endpoint_unknown_planner_type_returns_422():
    response = client.post(
        "/api/v1/planner/plan",
        json={"task": _STORE_TASK, "planner_type": "quantum_planner"},
    )
    assert response.status_code == 422
    assert response.json()["category"] == "invalid_planner_type"


def test_plan_endpoint_invalid_task_returns_success_false_not_500():
    # goal 'store' with no object/target -- InvalidTaskError inside the
    # planner, must surface as success=False, never a 500.
    response = client.post(
        "/api/v1/planner/plan", json={"task": {"task_type": "single", "goal": "store"}}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is False
    assert body["plan"] is None


def test_validate_endpoint_reports_precondition_violation():
    plan_response = client.post(
        "/api/v1/planner/plan", json={"task": _STORE_TASK, "planner_type": "rule_based"}
    )
    plan = plan_response.json()["plan"]
    # Break the plan: drop the "pickup" step so "place" has nothing to place.
    broken_plan = dict(plan)
    broken_plan["steps"] = [s for s in plan["steps"] if s["action"] != "pickup"]

    response = client.post(
        "/api/v1/planner/validate", json={"task": _STORE_TASK, "plan": broken_plan}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["valid"] is False
    assert any(issue["code"] == "precondition_failed" for issue in body["issues"])


def test_evaluate_endpoint_compares_all_planners_by_default():
    response = client.post("/api/v1/planner/evaluate", json={"task": _STORE_TASK})
    assert response.status_code == 200
    body = response.json()
    assert {r["planner_type"] for r in body["results"]} == {
        "rule_based",
        "react",
        "behavior_tree",
        "htn",
    }
    assert all(r["success"] for r in body["results"])


def test_evaluate_endpoint_respects_requested_subset():
    response = client.post(
        "/api/v1/planner/evaluate",
        json={"task": _STORE_TASK, "planner_types": ["rule_based"]},
    )
    assert response.status_code == 200
    body = response.json()
    assert len(body["results"]) == 1
    assert body["results"][0]["planner_type"] == "rule_based"


def test_evaluate_endpoint_unknown_planner_type_returns_422():
    response = client.post(
        "/api/v1/planner/evaluate",
        json={"task": _STORE_TASK, "planner_types": ["not_real"]},
    )
    assert response.status_code == 422
