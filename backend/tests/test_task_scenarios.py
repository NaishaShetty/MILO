"""
test_task_scenarios.py

End-to-end scenarios for the task library -- a request goes through the
phrasebook, the Orchestrator, a planner, the execution controller and a
`FakeSimulator` kitchen, and we check what actually ended up where. No
AI2-THOR, no LLM, no network.

Also covers the composite expansions ("clear the table", "tidy up"), the
question answerer, and learning from a mission (what the user told MILO,
and what each mission teaches it).
"""

from __future__ import annotations

import pytest
from _execution_test_helpers import FakeSimulator

from agents.execution_agent import ExecutionAgentWrapper
from agents.memory_agent import MemoryAgentWrapper
from agents.planner_agent import PlannerAgentWrapper
from agents.task_state import TaskStatus
from language.interpreter import InstructionInterpreter, Question
from memory.agent import MemoryAgent
from memory.config import MemoryConfig
from memory.habits import usual_places
from memory.models import MemoryType
from orchestration.answerer import QuestionAnswerer
from orchestration.composite import expand_composite
from orchestration.orchestrator import Orchestrator
from planner.factory import create_planner
from schemas.task import SingleTask

PLANNERS = ["rule_based", "htn", "behavior_tree", "react"]


def kitchen():
    def thing(oid, otype, distance, **extra):
        return {
            "objectId": oid,
            "objectType": otype,
            "distance": distance,
            "pickupable": extra.pop("pickupable", False),
            **extra,
        }

    return [
        thing("Apple|1", "Apple", 1.0, pickupable=True, parentReceptacles=["Table|1"]),
        thing("Mug|1", "Mug", 1.2, pickupable=True, parentReceptacles=["Table|1"]),
        thing("Book|1", "Book", 1.5, pickupable=True, parentReceptacles=["Table|1"]),
        thing("Table|1", "Table", 2.0),
        thing("CounterTop|1", "CounterTop", 2.5),
        thing("Shelf|1", "Shelf", 3.0),
        thing("Desk|1", "Desk", 3.1),
        thing("Fridge|1", "Fridge", 2.2, isOpen=False, openable=True),
        thing("LightSwitch|1", "LightSwitch", 1.8, isToggled=False),
        thing("Faucet|1", "Faucet", 2.8, isToggled=True),
    ]


def memory(tmp_path):
    config = MemoryConfig(
        enabled=True,
        database_path=tmp_path / "memory.db",
        vector_store_path=tmp_path / "vectors",
    )
    return MemoryAgentWrapper(MemoryAgent.from_config(config))


def run(text, planner="rule_based", *, sim=None, mem=None, interpreter=None):
    sim = sim or FakeSimulator(objects=kitchen())
    interpretation = (interpreter or InstructionInterpreter()).interpret(text)
    assert interpretation.kind == "task", (
        text,
        interpretation.kind,
        interpretation.message,
    )
    orchestrator = Orchestrator(
        PlannerAgentWrapper(create_planner(planner)),
        ExecutionAgentWrapper(sim),
        memory_agent=mem,
    )
    return orchestrator.run(interpretation.task), sim


def obj(sim, oid):
    return next(o for o in sim.objects if o["objectId"] == oid)


def actions(sim):
    return [(c["action"], c.get("object_id")) for c in sim.calls]


@pytest.mark.parametrize("planner", PLANNERS)
def test_fetch_brings_the_object_back_to_the_user(planner):
    state, sim = run("Could you grab me the mug?", planner)

    assert state.status == TaskStatus.SUCCEEDED, state.failures
    assert ("pickup", "Mug|1") in actions(sim)
    assert actions(sim)[-1] == ("navigate", "@home")  # walked back to the user
    assert [i["objectType"] for i in sim.inventory_objects] == ["Mug"]  # still carrying


@pytest.mark.parametrize("planner", PLANNERS)
def test_deliver_carries_the_object_to_the_destination(planner):
    state, sim = run("take the book to the desk", planner)

    assert state.status == TaskStatus.SUCCEEDED, state.failures
    assert actions(sim)[-2:] == [("pickup", "Book|1"), ("navigate", "Desk|1")][-2:] or (
        ("pickup", "Book|1") in actions(sim)
        and actions(sim)[-1] == ("navigate", "Desk|1")
    )


@pytest.mark.parametrize("planner", PLANNERS)
def test_put_something_in_a_container_opens_places_and_closes(planner):
    state, sim = run("put the apple in the fridge", planner)

    assert state.status == TaskStatus.SUCCEEDED, state.failures
    assert obj(sim, "Apple|1")["parentReceptacles"] == ["Fridge|1"]
    assert obj(sim, "Fridge|1")["isOpen"] is False  # closed again
    assert ("open", "Fridge|1") in actions(sim) and ("close", "Fridge|1") in actions(
        sim
    )


@pytest.mark.parametrize("planner", PLANNERS)
def test_put_something_on_a_surface_just_places_it(planner):
    state, sim = run("put the mug on the shelf", planner)

    assert state.status == TaskStatus.SUCCEEDED, state.failures
    assert obj(sim, "Mug|1")["parentReceptacles"] == ["Shelf|1"]
    assert not any(a in ("open", "close") for a, _ in actions(sim))


@pytest.mark.parametrize("planner", PLANNERS)
def test_open_then_close(planner):
    state, sim = run("open the fridge", planner)
    assert state.status == TaskStatus.SUCCEEDED, state.failures
    assert obj(sim, "Fridge|1")["isOpen"] is True

    state, sim = run("close the fridge", planner, sim=sim)
    assert state.status == TaskStatus.SUCCEEDED, state.failures
    assert obj(sim, "Fridge|1")["isOpen"] is False


@pytest.mark.parametrize("planner", PLANNERS)
def test_turn_things_on_and_off(planner):
    state, sim = run("turn on the lights", planner)
    assert state.status == TaskStatus.SUCCEEDED, state.failures
    assert obj(sim, "LightSwitch|1")["isToggled"] is True

    state, sim = run("switch the tap off", planner, sim=sim)
    assert state.status == TaskStatus.SUCCEEDED, state.failures
    assert obj(sim, "Faucet|1")["isToggled"] is False


def test_turning_on_something_already_on_does_nothing():
    state, sim = run("turn on the tap")  # the faucet is already running
    assert state.status == TaskStatus.SUCCEEDED
    assert sim.calls == []


@pytest.mark.parametrize("planner", PLANNERS)
def test_find_reports_where_the_thing_is(planner, tmp_path):
    state, sim = run("find the mug", planner, mem=memory(tmp_path))

    assert state.status == TaskStatus.SUCCEEDED, state.failures
    assert state.answer == "The mug is on the table."
    assert state.learned == ["The mug is on the table."]


@pytest.mark.parametrize("planner", PLANNERS)
def test_clear_the_table_moves_everything_to_the_destination(planner):
    state, sim = run("clear the table onto the counter", planner)

    assert state.status == TaskStatus.SUCCEEDED, state.failures
    for oid in ("Apple|1", "Mug|1", "Book|1"):
        assert obj(sim, oid)["parentReceptacles"] == ["CounterTop|1"], oid
    assert sorted(g["object"] for g in state.sub_goals) == ["apple", "book", "mug"]
    assert not sim.inventory_objects


def test_clearing_an_already_clear_table_says_so():
    sim = FakeSimulator(objects=[o for o in kitchen() if not o.get("pickupable")])
    state, sim = run("clear the table onto the counter", sim=sim)
    assert state.status == TaskStatus.SUCCEEDED
    assert state.answer == "The table is already clear."
    assert sim.calls == []


# -- tidy up & remembering what the user said ------------------------------


def _teach(mem, *sentences):
    interpreter = InstructionInterpreter()
    for sentence in sentences:
        pref = interpreter.interpret(sentence).preference
        assert pref is not None, sentence
        assert mem.remember_preference(pref.object, pref.relation, pref.place)


@pytest.mark.parametrize("planner", PLANNERS)
def test_tidy_up_puts_things_back_where_memory_says_they_live(planner, tmp_path):
    mem = memory(tmp_path)
    _teach(mem, "the mug goes on the shelf", "the apple goes in the fridge")

    state, sim = run("tidy up", planner, mem=mem)

    assert state.status == TaskStatus.SUCCEEDED, state.failures
    assert obj(sim, "Mug|1")["parentReceptacles"] == ["Shelf|1"]
    assert obj(sim, "Apple|1")["parentReceptacles"] == ["Fridge|1"]
    # The book has no known home: left alone.
    assert obj(sim, "Book|1")["parentReceptacles"] == ["Table|1"]


def test_tidy_up_with_nothing_remembered_asks_to_be_taught(tmp_path):
    state, sim = run("tidy up", mem=memory(tmp_path))
    assert state.status == TaskStatus.SUCCEEDED
    assert "Tell me" in state.answer and sim.calls == []


def test_a_user_preference_beats_something_merely_observed(tmp_path):
    mem = memory(tmp_path)
    # A mission puts the mug on the counter (observed), later the user says shelf.
    run("put the mug on the counter", mem=mem)
    first = mem.usual_places()["mug"]
    assert first[0] == "counter"
    _teach(mem, "the mug goes on the shelf")
    assert mem.usual_places()["mug"] == ("shelf", "located_on")


def test_each_mission_writes_what_it_learned(tmp_path):
    mem = memory(tmp_path)
    state, _ = run("put the apple in the fridge", mem=mem)

    assert state.learned == ["The apple goes in the fridge."]
    assert any(m["memory_type"] == "semantic" for m in state.created_memories)
    assert mem.usual_places()["apple"] == ("fridge", "stored_in")


def test_forgetting_a_memory_takes_the_habit_out_of_play(tmp_path):
    from memory.models import MemoryStatus

    mem = memory(tmp_path)
    _teach(mem, "the mug goes on the shelf")
    manager = mem._memory_agent.engine.manager
    memory_ = manager.list(memory_type=MemoryType.USER)[0]
    memory_.status = MemoryStatus.ARCHIVED
    manager.update(memory_)
    assert "mug" not in mem.usual_places()


def test_put_it_away_uses_the_remembered_place(tmp_path):
    mem = memory(tmp_path)
    _teach(mem, "the mug goes on the shelf")
    interpreter = InstructionInterpreter(
        usual_place=lambda name: mem.usual_places().get(name)
    )

    state, sim = run("put the mug away", mem=mem, interpreter=interpreter)

    assert state.status == TaskStatus.SUCCEEDED, state.failures
    assert obj(sim, "Mug|1")["parentReceptacles"] == ["Shelf|1"]


# -- a remembered place is tried first --------------------------------------


def test_the_remembered_place_is_searched_first(tmp_path):
    mem = memory(tmp_path)
    _teach(mem, "the mug goes on the shelf")
    state, sim = run("find the mug", mem=mem)

    plan_steps = [(s.action, s.target) for s in state.current_plan.steps]
    assert plan_steps[:2] == [("locate", "shelf"), ("navigate", "shelf")]
    assert state.current_plan.steps[0].parameters.get("source") == "memory"


# -- composite expansion on its own --------------------------------------------


def test_expand_clear_table_picks_a_container_or_a_surface_per_destination():
    meta = {"objects": kitchen()}
    onto = expand_composite(
        SingleTask(
            goal="clear_table", source_location="table", target_location="counter"
        ),
        meta,
    )
    assert {s.goal for s in onto.subtasks} == {"place"}
    into = expand_composite(
        SingleTask(
            goal="clear_table", source_location="table", target_location="fridge"
        ),
        meta,
    )
    assert {s.goal for s in into.subtasks} == {"store"}


def test_expand_clear_table_with_no_destination_or_no_table():
    meta = {"objects": kitchen()}
    ask = expand_composite(
        SingleTask(goal="clear_table", source_location="table"), meta
    )
    assert not ask.subtasks and "Where should I put" in ask.message
    nope = expand_composite(
        SingleTask(goal="clear_table", source_location="sofa", target_location="shelf"),
        meta,
    )
    assert "can't see a sofa" in nope.message


def test_expand_tidy_up_leaves_things_that_are_already_home():
    objects = kitchen()
    obj_ = next(o for o in objects if o["objectId"] == "Mug|1")
    obj_["parentReceptacles"] = ["Shelf|1"]
    result = expand_composite(
        SingleTask(goal="tidy_up"),
        {"objects": objects},
        {"mug": ("shelf", "located_on")},
    )
    assert result.subtasks == [] and "already where it usually lives" in result.message


# -- answering questions without acting -------------------------------------------


def _answer(question, objects=None, recall=None):
    meta = {"objects": objects or kitchen(), "inventoryObjects": []}
    return QuestionAnswerer(lambda: meta, recall).answer(question)


def test_is_it_open_or_on():
    assert _answer(Question("is_open", "fridge", True)) == "No, the fridge is closed."
    assert _answer(Question("is_open", "fridge", False)) == "Yes, the fridge is closed."
    assert _answer(Question("is_on", "tap", True)) == "Yes, the tap is on."
    assert "can't be opened" in _answer(Question("is_open", "mug", True))
    assert "can't see a toaster" in _answer(Question("is_open", "toaster", True))


def test_where_is_it():
    assert _answer(Question("where", "mug")) == "The mug is on the table."
    assert _answer(Question("where", "toaster")).startswith("I can't see a toaster")
    recalled = _answer(
        Question("where", "toaster"), recall=lambda n: ("counter", "located_on")
    )
    assert "usually being on the counter" in recalled


def test_holding_and_seeing():
    assert _answer(Question("holding")) == "My hands are empty."
    meta = {
        "objects": [],
        "inventoryObjects": [{"objectId": "Apple|1", "objectType": "Apple"}],
    }
    assert (
        QuestionAnswerer(lambda: meta).answer(Question("holding"))
        == "I'm holding the apple."
    )
    visible = [dict(o, visible=True) for o in kitchen()[:2]]
    assert _answer(Question("see"), visible) == "I can see apple, mug."


def test_usual_places_prefers_the_user_then_confidence_then_recency(tmp_path):
    mem = memory(tmp_path)
    mem.remember_observation(
        "cup", "located_on", "counter", provenance=_obs(), confidence=0.99
    )
    mem.remember_preference("cup", "located_on", "shelf", confidence=0.5)
    assert usual_places(mem._memory_agent.list_memories())["cup"][0] == "shelf"


def _obs():
    from memory.models import MemoryProvenance

    return MemoryProvenance.OBSERVATION
