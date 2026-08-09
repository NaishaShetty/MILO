"""
model_config.py

Purpose
-------
Single source of truth for "where does each AI model live and how
should it be loaded." Every model this project uses (Grounding DINO
today; SAM2, Depth Anything, Florence-2, Whisper tomorrow) gets one
`ModelConfig` entry here.

Responsibilities
----------------
- Declare the on-disk layout: all models live under the repository's
  top-level `models/` directory, one subfolder per model, so the
  project is self-contained and reproducible (no dependency on a
  user's `~/.cache/huggingface`).
- Declare the Hugging Face Hub identifier used to fetch a model the
  first time it's needed.
- Declare device selection policy (`get_device`) in one place instead
  of every detector/agent independently probing `torch.cuda`.

Why this abstraction is needed
-------------------------------
Without it, every detector class (Grounding DINO, SAM2, Florence-2, ...)
would hardcode its own `MODEL_NAME` string and its own notion of where
weights should be cached. That scatters model lifecycle knowledge across
the codebase and makes it impossible to, for example, switch every model
to a shared network drive, swap a model's Hub revision, or audit "what
models does this project depend on" without grepping every file.

`ModelConfig` is deliberately a plain, frozen dataclass rather than a
dict: dict-based config (`GROUNDING_DINO = {"hf_name": ...}`) has no
schema, so a typo in a key name (`"hf_nmae"`) fails silently or with a
confusing `KeyError` far from the mistake. A dataclass gives static
attribute access, autocomplete, and a single documented shape that every
future model config must conform to.

This file intentionally does NOT know how to download or load a model
-- that behavior belongs to `ModelManager` (model_manager.py). This file
is pure data/declaration, which keeps it trivial to read, diff, and
extend when a new model is added.
"""

from dataclasses import dataclass
from pathlib import Path

import torch

# ---------------------------------------------------------------------
# Filesystem layout
# ---------------------------------------------------------------------
# backend/config/model_config.py -> parents[1] is the repository root
# (backend/config -> backend -> <repo root>). Models live at
# <repo root>/models/<model_name>/, a sibling of backend/, matching the
# project's existing top-level layout (models/, frontend/, backend/, ...).
REPO_ROOT = Path(__file__).resolve().parents[2]
MODELS_ROOT = REPO_ROOT / "models"


@dataclass(frozen=True)
class ModelConfig:
    """
    Everything needed to locate and materialize one model.

    Attributes
    ----------
    name:
        Short identifier used for logging and registry lookup,
        e.g. "grounding_dino".
    hf_name:
        Hugging Face Hub repo id to download from when no local
        copy exists yet, e.g. "IDEA-Research/grounding-dino-base".
    local_dir:
        Project-local directory the model is stored in and loaded
        from. Never the global Hugging Face cache.
    """

    name: str
    hf_name: str
    local_dir: Path


# ---------------------------------------------------------------------
# Device policy
# ---------------------------------------------------------------------
def get_device() -> str:
    """
    Central device selection so every model agrees on GPU vs CPU
    instead of each detector re-deriving it independently.
    """
    return "cuda" if torch.cuda.is_available() else "cpu"


# ---------------------------------------------------------------------
# Model registry
# ---------------------------------------------------------------------
# Grounding DINO is wired up and in active use (backend/vision/detector.py).
GROUNDING_DINO = ModelConfig(
    name="grounding_dino",
    hf_name="IDEA-Research/grounding-dino-base",
    local_dir=MODELS_ROOT / "grounding_dino",
)

# NOT the official facebook/sam2-hiera-base-plus-hf repo: verified (by
# loading it and inspecting for "newly initialized" / "not used" weight
# warnings) that its model.safetensors uses stale parameter names
# (`image_encoder.*`, `sam_mask_decoder.*`) that don't match any version
# of transformers' Sam2Model, past or present (checked v4.57.6 through
# the current main branch, both use `vision_encoder.*`/`mask_decoder.*`)
# -- it loads without error but with the mask decoder and vision encoder
# silently randomly initialized. Same problem confirmed on the tiny
# checkpoint too, so it's a repo-wide issue, not specific to this size.
#
# danelcsb/* are community re-conversions of the same Meta weights with
# parameter names matching the current transformers Sam2Model.
# Safetensors format (no arbitrary code execution risk), but these are
# not official facebook/huggingface repos, so they carry no upstream
# support guarantee.
#
# `danelcsb/sam2_hiera_base_plus` was tried first and rejected: its
# config.json and model.safetensors disagree with each other (a Linear
# layer's checkpoint shape is 112, the config says 96 -- 96 is Hiera
# tiny/small's embed_dim, 112 is base_plus's, so this looks like a
# mislabeled upload with the wrong config or wrong weights attached).
# It fails with a `RuntimeError` on load, not a silent wrong-weights
# problem, so at least it's a loud failure.
#
# `danelcsb/sam2.1_hiera_tiny` was verified to load with a completely
# clean, unfiltered output -- no shape errors, no "newly initialized"
# or "not used" weight warnings. It's the smaller/faster/lower-accuracy
# end of the SAM2 family. Revisit upgrading to a larger size once a
# verified-consistent base_plus (or larger) conversion is found -- this
# was chosen because it's the smallest thing proven to actually work,
# not because tiny is the target size.
SAM2 = ModelConfig(
    name="sam2",
    hf_name="danelcsb/sam2.1_hiera_tiny",
    local_dir=MODELS_ROOT / "sam2",
)

DEPTH_ANYTHING = ModelConfig(
    name="depth_anything",
    hf_name="depth-anything/Depth-Anything-V2-Small-hf",
    local_dir=MODELS_ROOT / "depth_anything",
)

FLORENCE2 = ModelConfig(
    name="florence2",
    hf_name="microsoft/Florence-2-base",
    local_dir=MODELS_ROOT / "florence2",
)

WHISPER = ModelConfig(
    name="whisper",
    hf_name="openai/whisper-base",
    local_dir=MODELS_ROOT / "whisper",
)

# Generic lookup by name, e.g. for CLI tooling ("predownload every model")
# or a future admin endpoint. Keeping this alongside the named constants
# means callers can use whichever access pattern fits: `GROUNDING_DINO`
# for a known compile-time dependency, `MODEL_REGISTRY["grounding_dino"]`
# for a name resolved at runtime.
MODEL_REGISTRY = {
    config.name: config
    for config in (GROUNDING_DINO, SAM2, DEPTH_ANYTHING, FLORENCE2, WHISPER)
}
