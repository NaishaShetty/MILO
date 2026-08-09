# .github/

Purpose
-------
Home for GitHub-native project automation and templates: CI workflows
(`.github/workflows/`), issue/PR templates, and any other file GitHub
gives special meaning to by virtue of living in this directory.

Current contents
-----------------
- `workflows/ci.yml` -- runs on every push and pull request: installs
  `backend/requirements.txt` on Python 3.9, then runs formatting
  (`black --check`), linting (`ruff check`), type-checking (`mypy`),
  and the unit test suite (`pytest backend/tests/`), failing on the
  first check that fails. Configuration lives in the repository root's
  `pyproject.toml`. Simulator-dependent integration tests (anything
  that launches AI2-THOR or loads model weights, e.g.
  `backend/vision/scene_graph/test_scene_graph.py`) are not collected
  as pytest tests and are not expected to run in standard CI without a
  GPU/simulator-capable runner.

Planned contents
-----------------
- Issue and pull-request templates, once the project has outside
  contributors to standardize intake for.
