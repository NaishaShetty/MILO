"""
test_api_vision.py

Purpose
-------
Verifies `POST /api/v1/vision/perceive` behaves as a thin HTTP wrapper
around a `VisionSystem`: it validates the request body, delegates to an
injected fake `VisionSystem` (via `app.dependency_overrides`, never a
real simulator/model), serializes the resulting `Scene` into the API's
`SpatialObject`/`PerceptionStatus` shapes, and returns a clean 503 when
no vision system was constructed at startup. No AI2-THOR, GPU, or model
weights anywhere in this suite -- mirrors `test_api_language.py`'s
mocking discipline one layer up.
"""

from __future__ import annotations

from typing import Iterator
from unittest.mock import MagicMock

import numpy as np
import pytest
from fastapi.testclient import TestClient

from api.app import app
from api.routes.vision import get_vision_system
from scene.detection import Detection
from scene.metadata_keys import SceneMetadata
from scene.scene import Scene
from vision.temporal.scene_diff import ChangeType, SceneChange
from vision.tracking.track import Track, TrackStatus


def _override_vision_system(fake_system) -> None:
    app.dependency_overrides[get_vision_system] = lambda: fake_system


@pytest.fixture(autouse=True)
def _clear_overrides():
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client


def _fake_image():
    return np.zeros((20, 20, 3), dtype=np.uint8)


def _build_fake_vision_system(scene: Scene, changes=None, tracks=None):
    fake_agent = MagicMock()
    fake_agent.perceive.return_value = scene
    fake_agent.get_rgb_image.return_value = _fake_image()

    fake_tracker = MagicMock()
    fake_tracker.tracks = tracks or {}

    fake_temporal_scene = MagicMock()
    fake_temporal_scene.update.return_value = changes or []

    fake_system = MagicMock()
    fake_system.agent = fake_agent
    fake_system.tracker = fake_tracker
    fake_system.temporal_scene = fake_temporal_scene

    return fake_system


def test_perceive_returns_objects_and_status(client: TestClient) -> None:
    scene = Scene()
    detection = Detection(label="mug", confidence=0.9, bbox=[1, 1, 10, 10])
    detection.tracking_id = 3
    detection.depth = 1.5
    detection.position_3d = [0.1, 0.2, 1.5]
    detection.attributes["track_status"] = "tracked"
    scene.add_detection(detection)
    scene.metadata[SceneMetadata.DEPTH_SOURCE] = "ground_truth"

    track = Track(
        track_id=3,
        label="mug",
        first_seen=1,
        last_seen=5,
        frame_count=5,
        current_bbox=[1, 1, 10, 10],
        previous_bbox=None,
        current_position_3d=[0.1, 0.2, 1.5],
        previous_position_3d=None,
        status=TrackStatus.TRACKED,
        confidence=0.9,
        missed_frames=0,
    )

    fake_system = _build_fake_vision_system(scene, tracks={3: track})
    _override_vision_system(fake_system)

    response = client.post("/api/v1/vision/perceive", json={"prompt": "mug."})

    assert response.status_code == 200
    body = response.json()

    assert body["status"]["object_count"] == 1
    assert body["status"]["tracked_count"] == 1
    assert body["status"]["depth_available_count"] == 1
    assert body["status"]["depth_source"] == "ground_truth"

    obj = body["objects"][0]
    assert obj["object_id"] == 3
    assert obj["label"] == "mug"
    assert obj["depth"] == pytest.approx(1.5)
    assert obj["position_3d"] == pytest.approx([0.1, 0.2, 1.5])
    assert obj["track_status"] == "tracked"
    assert obj["frames_observed"] == 5
    assert obj["first_seen"] == 1
    assert obj["last_seen"] == 5

    assert isinstance(body["camera_image_png_b64"], str)
    assert len(body["camera_image_png_b64"]) > 0


def test_perceive_includes_scene_changes(client: TestClient) -> None:
    scene = Scene()
    changes = [
        SceneChange(
            change_type=ChangeType.NEW, tracking_id=1, label="apple", detail="x"
        )
    ]
    fake_system = _build_fake_vision_system(scene, changes=changes)
    _override_vision_system(fake_system)

    response = client.post("/api/v1/vision/perceive", json={"prompt": "apple."})

    assert response.status_code == 200
    body = response.json()
    assert body["scene_changes"] == [
        {"change_type": "new", "tracking_id": 1, "label": "apple", "detail": "x"}
    ]


def test_perceive_without_depth_image_omits_depth_fields(client: TestClient) -> None:
    scene = Scene()  # no depth_image set
    fake_system = _build_fake_vision_system(scene)
    _override_vision_system(fake_system)

    response = client.post("/api/v1/vision/perceive", json={"prompt": "mug."})

    assert response.status_code == 200
    body = response.json()
    assert body["depth_image_png_b64"] is None
    assert body["depth_legend"] is None


def test_perceive_returns_503_when_vision_system_unavailable(
    client: TestClient,
) -> None:
    # Exercises the real `get_vision_system` dependency (not an
    # override) with `app.state.vision_system` set the way `_lifespan`
    # leaves it when simulator startup fails -- see `api/app.py`'s
    # docstring.
    original = app.state.vision_system
    app.state.vision_system = None
    try:
        response = client.post("/api/v1/vision/perceive", json={"prompt": "mug."})
    finally:
        app.state.vision_system = original

    assert response.status_code == 503
    body = response.json()
    assert body["category"] == "vision_unavailable"


def test_perceive_rejects_empty_prompt(client: TestClient) -> None:
    # A configured vision system is injected so this test isolates
    # request-body validation from the separate "no vision system"
    # 503 path already covered above.
    _override_vision_system(_build_fake_vision_system(Scene()))

    response = client.post("/api/v1/vision/perceive", json={"prompt": ""})

    assert response.status_code == 422


def test_perceive_rejects_missing_prompt_field(client: TestClient) -> None:
    _override_vision_system(_build_fake_vision_system(Scene()))

    response = client.post("/api/v1/vision/perceive", json={})

    assert response.status_code == 422
