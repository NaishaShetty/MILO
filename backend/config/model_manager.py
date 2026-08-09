"""
model_manager.py

Purpose
-------
Owns the full lifecycle of a model on disk: does a local copy exist,
should one be downloaded, is what's on disk valid, and finally how to
load it into a `(processor, model)` pair on the right device.

Responsibilities
----------------
- Resolve a `ModelConfig` to a local directory.
- Detect whether that directory already holds a usable model, purely
  from the local filesystem -- this check never touches the network,
  which is what makes "local copy exists -> load it, no Hub traffic"
  possible.
- Download from the Hugging Face Hub straight into the project's
  `models/<name>/` directory (not `~/.cache/huggingface`) when no
  local copy exists.
- Load the model through whatever `transformers` Auto* classes the
  caller supplies, so this file stays agnostic to what kind of model
  (detection, segmentation, depth, speech, ...) it is handling.

Why this abstraction is needed
-------------------------------
Every detector was on a path to reimplementing "check if downloaded,
download if not, then load" itself, with its own bugs and its own
opinion about where files go. `ModelManager` centralizes that so a new
detector (SAM2Detector, FlorenceDetector, ...) is a ~15-line class that
delegates lifecycle management here and only implements the parts that
are genuinely model-specific (its inference method).

Splitting this from `ModelConfig` follows single-responsibility:
`ModelConfig` is inert data describing a model, `ModelManager` is the
behavior that acts on that data. A config object should be safe to
import anywhere (including tests, tooling, docs generation) without
pulling in `transformers` or triggering filesystem/network side
effects; only constructing a `ModelManager` and calling its methods
does that.

Versioning note
----------------
`ModelConfig` does not yet pin a Hub revision/commit hash, so
`is_downloaded()` treats "directory has a config.json" as sufficient
and will not detect an upstream model update. When version pinning
matters (e.g. reproducing a specific experiment), add a `revision`
field to `ModelConfig` and pass it through to `snapshot_download`
here -- the rest of the call sites do not need to change.
"""

from pathlib import Path
from typing import Optional, Tuple

from huggingface_hub import snapshot_download

from config.model_config import ModelConfig, get_device

# Files actually needed to load a `transformers` processor + model.
# Excludes alternate weight formats (`pytorch_model.bin`,
# `*.msgpack`, `*.h5`, ...) that Hugging Face repos often carry
# alongside `*.safetensors` for backwards compatibility -- downloading
# both formats silently doubles storage for no benefit, since
# `from_pretrained` only ever loads one. `*.json`/`*.txt` cover the
# various config/tokenizer/vocab files by extension so this list does
# not need a new entry every time a model repo names them slightly
# differently.
DEFAULT_ALLOW_PATTERNS = [
    "config.json",
    "model.safetensors",
    "preprocessor_config.json",
    "processor_config.json",
    "tokenizer*",
    "special_tokens_map.json",
    "*.json",
    "*.txt",
]


class ModelManager:
    """
    Resolves, downloads, validates, and loads a single model described
    by a `ModelConfig`.
    """

    def __init__(self, config: ModelConfig):
        self.config = config

    def is_downloaded(self) -> bool:
        """
        True if `local_dir` already contains a usable snapshot.

        Checked purely on the local filesystem (no network call) so
        that the common case -- model already downloaded -- never
        waits on Hugging Face Hub availability or rate limits.
        """
        local_dir = self.config.local_dir

        if not local_dir.exists():
            return False

        return any(local_dir.glob("config.json"))

    def download(self) -> None:
        """
        Fetch the model from the Hugging Face Hub directly into
        `local_dir`, so all subsequent loads are fully local.
        """
        print(
            f"[ModelManager] '{self.config.name}' not found locally. "
            f"Downloading {self.config.hf_name} -> {self.config.local_dir}"
        )

        self.config.local_dir.mkdir(parents=True, exist_ok=True)

        snapshot_download(
            repo_id=self.config.hf_name,
            local_dir=str(self.config.local_dir),
            allow_patterns=DEFAULT_ALLOW_PATTERNS,
        )

        print(f"[ModelManager] Download complete: {self.config.local_dir}")

    def ensure_available(self) -> Path:
        """
        Guarantee `local_dir` holds a usable model, downloading only
        if necessary. Returns the local directory to load from.
        """
        if not self.is_downloaded():
            self.download()

        return self.config.local_dir

    def load(
        self,
        processor_cls,
        model_cls,
        device: Optional[str] = None,
    ) -> Tuple[object, object]:
        """
        Ensure the model is available locally, then load it.

        Parameters
        ----------
        processor_cls, model_cls:
            The `transformers` Auto* classes appropriate for this
            model, e.g. `AutoProcessor` / `AutoModelForZeroShotObjectDetection`.
            Kept as parameters (rather than hardcoded here) so this
            method works for every model type without modification.
        device:
            Overrides the project's default device policy
            (`config.model_config.get_device`) for this load only.

        Returns
        -------
        (processor, model) with `model` already moved to the target
        device.
        """
        local_dir = self.ensure_available()
        device = device or get_device()

        processor = processor_cls.from_pretrained(str(local_dir))
        model = model_cls.from_pretrained(str(local_dir)).to(device)

        return processor, model
