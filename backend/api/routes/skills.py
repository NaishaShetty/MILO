"""
skills.py (backend/api/routes)

Skills MILO has learned or been taught (`novel.skills`):

    GET    /api/v1/skills                    every skill, most recently used first
    PATCH  /api/v1/skills/{id}               rename, change status, or edit the steps
    DELETE /api/v1/skills/{id}
    POST   /api/v1/skills/from-task/{id}     "Save as skill" after a mission that worked
    POST   /api/v1/skills/teach              "Teach MILO": steps in words -> run back -> save

A taught skill is stored as `teaching` and immediately run once ("let me show you
what I understood"); it becomes a `candidate` when that run succeeds.
"""

from __future__ import annotations

from typing import List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field

from agents.task_state import InputSource
from api.routes.tasks import _store, _TaskAlreadyRunningError, get_simulator
from novel.factory import shared_library
from novel.skills import SkillChainError, templatize
from novel.teach import TeachError, proposal_from_task, proposal_from_words
from schemas.task import SingleTask
from simulator.simulator import Simulator

router = APIRouter()


class SkillStep(BaseModel):
    action: str
    target: Optional[str] = None
    container: Optional[str] = None


class EditSkill(BaseModel):
    name: Optional[str] = Field(default=None, max_length=80)
    status: Optional[Literal["candidate", "trusted", "disabled"]] = None
    steps: Optional[List[SkillStep]] = None


class SaveFromTask(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    wording: Optional[str] = Field(default=None, max_length=200)


class Teach(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    wording: str = Field(min_length=1, max_length=200)
    steps: List[str] = Field(min_length=1, max_length=20)


def _bad(message: str, status: int = 400) -> HTTPException:
    return HTTPException(
        status_code=status, detail={"category": "skill", "message": message}
    )


def _scene_names(simulator: Simulator) -> List[str]:
    try:
        meta = simulator.get_metadata() or {}
    except Exception:
        meta = {}
    return [str(o.get("objectType", "")).lower() for o in meta.get("objects") or []]


@router.get("", summary="Every skill MILO knows")
def list_skills() -> dict:
    return {"skills": [s.to_dict() for s in shared_library().all()]}


@router.patch("/{skill_id}", summary="Rename, enable/disable, or edit a skill")
def edit_skill(skill_id: str, body: EditSkill) -> dict:
    library = shared_library()
    skill = library.by_id(skill_id)
    if skill is None:
        raise _bad("I don't have that skill.", 404)
    try:
        if body.steps is not None:
            library.update_steps(skill_id, [s.model_dump() for s in body.steps])
        if body.name:
            library.rename(skill_id, body.name)
        if body.status:
            library.set_status(skill.template, body.status)
    except SkillChainError as exc:
        raise _bad(str(exc)) from exc
    return library.by_id(skill_id).to_dict()  # type: ignore[union-attr]


@router.delete("/{skill_id}", summary="Forget a skill")
def delete_skill(skill_id: str) -> dict:
    if not shared_library().delete(skill_id):
        raise _bad("I don't have that skill.", 404)
    return {"deleted": skill_id}


@router.post("/from-task/{task_id}", summary="Save a mission that worked as a skill")
def save_from_task(
    task_id: str, body: SaveFromTask, simulator: Simulator = Depends(get_simulator)
) -> dict:
    state = _store.get(task_id)
    if state is None:
        raise _bad("I can't find that mission.", 404)
    try:
        proposal, used = proposal_from_task(state)
        wording = (body.wording or state.user_request).strip()
        skill = shared_library().save(
            body.name,
            wording,
            proposal,
            sorted(set(used) | set(_scene_names(simulator))),
        )
    except (TeachError, SkillChainError) as exc:
        raise _bad(str(exc)) from exc
    return skill.to_dict()


@router.post("/teach", status_code=202, summary="Teach MILO a skill in words")
def teach(
    body: Teach, response: Response, simulator: Simulator = Depends(get_simulator)
) -> dict:
    try:
        meta = simulator.get_metadata()
    except Exception:
        meta = None
    names = _scene_names(simulator)
    try:
        proposal = proposal_from_words(body.steps, meta, goal=body.name)
        template, _ = templatize(body.wording, names)
        if "{o" not in template:
            raise TeachError(
                "Mention at least one object in the wording (for example "
                '"set the mug on the table"), so I can use the skill with other things.'
            )
        skill = shared_library().save(
            body.name, body.wording, proposal, names, status="teaching"
        )
    except (TeachError, SkillChainError) as exc:
        raise _bad(str(exc)) from exc
    # Show what was understood by doing it once, now.
    try:
        state = _store.start(
            SingleTask(goal="novel", estimated_goal=body.wording.strip()),
            InputSource.TEXT,
            "novel",
        )
    except _TaskAlreadyRunningError:
        response.status_code = 200
        return {
            "skill": skill.to_dict(),
            "task": None,
            "message": "Saved. I'm busy right now, so I'll try it the next time you ask.",
        }
    return {
        "skill": skill.to_dict(),
        "task": state.to_dict(),
        "message": "Let me show you what I understood.",
    }
