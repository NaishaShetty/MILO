"""
test_vision_factory.py

Purpose
-------
Covers `vision/factory.py::build_depth_estimator`'s dispatch logic
without loading any real model. The ground-truth path is exercised
directly (it only binds a callable, no model weights); the
`depth_anything` path is *not* instantiated here (it downloads/loads a
real model in `__init__` -- out of scope for CI, see
`vision/depth/depth_anything_estimator.py`'s docstring) -- only that an
unrecognized `depth_source` raises is tested for the dispatch branch
that guards it.
"""

import pytest

from simulator.simulator import Simulator
from vision.depth.ground_truth_depth_estimator import GroundTruthDepthEstimator
from vision.factory import (
    DEPTH_SOURCE_GROUND_TRUTH,
    build_depth_estimator,
)


def test_ground_truth_depth_source_binds_simulator_get_depth():
    simulator = Simulator(render_depth=True)

    estimator = build_depth_estimator(DEPTH_SOURCE_GROUND_TRUTH, simulator, None)

    assert isinstance(estimator, GroundTruthDepthEstimator)


def test_unknown_depth_source_raises():
    simulator = Simulator()

    with pytest.raises(ValueError):
        build_depth_estimator("not_a_real_source", simulator, None)
