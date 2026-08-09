"""
backend/evaluation

Purpose
-------
Phase 3.6 (Testing & Benchmarking) evaluation framework for the
Language Parsing Runtime (`backend/language/`). This package treats
`language.agent.LanguageAgent` as the system under test: it loads the
Phase 3.3 benchmark datasets (`datasets/language/evaluation/`), drives
them through the agent's existing public interface
(`parse_with_diagnostics`), scores the results field-by-field against
each dataset's expectations, and aggregates the scores into
reproducible, versioned metrics -- accuracy, recovery rate, latency,
provider comparisons, prompt-version comparisons.

Why this is a separate top-level package, not part of `language/`
-------------------------------------------------------------------
`backend/language/` is the runtime being measured. Nothing in this
package may be imported by `backend/language/*`, and nothing in this
package may special-case its behavior to make a benchmark score look
better -- see `dataset_loader.py`, `benchmark_runner.py`, and each
other module's docstring for how that boundary is kept concrete rather
than aspirational.
"""
