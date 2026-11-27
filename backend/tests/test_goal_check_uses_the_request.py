"""The end-of-mission check holds a plan to what was asked, not only to the conditions
the plan wrote for itself (found by the local-model benchmark: asked to fetch a missing
mug, the model fetched an apple, stated "holding the apple", and passed)."""

from __future__ import annotations

from agents.execution_agent import ExecutionAgentWrapper
from agents.planner_agent import PlannerAgentWrapper
from learning.synthetic import Faults, SyntheticSimulator
from novel.eval_novel import P, S, plan, scene
from novel.planner import NovelPlanner
from novel.safety import Constraints
from novel.skills import SkillLibrary
from orchestration.orchestrator import Orchestrator
from schemas.task import SingleTask


class FetchesTheApple:
    """A model that answers every request with "fetch the apple"."""

    name = "test"

    def propose(self, request):
        steps = [S("locate", "apple"), S("navigate", "apple"), S("pickup", "apple")]
        return plan("fetch the apple", steps, [P("held", "apple")])


def _run(task, tmp_path, faults=Faults()):
    sim = SyntheticSimulator(scene(), faults)
    execution = ExecutionAgentWrapper(sim)  # type: ignore[arg-type]
    novel = NovelPlanner(FetchesTheApple(), execution.get_metadata,
                         constraints=Constraints.load(), skills=SkillLibrary(tmp_path / "s.db"))  # fmt: skip
    return Orchestrator(PlannerAgentWrapper(novel), execution).run(task)  # type: ignore[arg-type]


def test_fetching_the_wrong_object_fails_a_request_for_the_mug(tmp_path):
    state = _run(SingleTask(goal="fetch", object="mug"), tmp_path,
                 Faults(kind="missing_object", target="mug"))  # fmt: skip
    assert state.status.value == "failed"
    checked = {(v["kind"], v["object"]): v["ok"] for v in state.verification}
    assert checked[("held", "mug")] is False and checked[("held", "apple")] is True


def test_a_novel_command_is_still_judged_by_the_plans_own_conditions(tmp_path):
    state = _run(
        SingleTask(goal="novel", estimated_goal="get me something to eat"), tmp_path
    )
    assert state.status.value == "succeeded"
    assert [(v["kind"], v["object"]) for v in state.verification] == [("held", "apple")]
