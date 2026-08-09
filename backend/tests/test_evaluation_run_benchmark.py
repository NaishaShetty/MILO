"""
test_evaluation_run_benchmark.py

Purpose
-------
Verifies `evaluation.run_benchmark`'s cost/safety gate --
`_require_real_execution_enabled` -- raises `BenchmarkConfigurationError`
whenever `RUN_LLM_BENCHMARK` is not exactly `"true"`, regardless of
whether a provider API key happens to be present. This test never
calls a real LLM provider and never needs network access: it only
exercises the gate itself, mirroring `test_language_llm_smoke.py`'s
"the real-network path stays opt-in" convention without actually
opting in.
"""

from __future__ import annotations

import pytest

from evaluation.exceptions import BenchmarkConfigurationError
from evaluation.run_benchmark import _require_real_execution_enabled


class TestRealExecutionGate:
    def test_missing_env_var_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("RUN_LLM_BENCHMARK", raising=False)
        with pytest.raises(BenchmarkConfigurationError):
            _require_real_execution_enabled()

    def test_env_var_present_but_not_true_raises(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("RUN_LLM_BENCHMARK", "1")
        with pytest.raises(BenchmarkConfigurationError):
            _require_real_execution_enabled()

    def test_api_key_alone_is_never_sufficient(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("RUN_LLM_BENCHMARK", raising=False)
        monkeypatch.setenv("OPENAI_API_KEY", "sk-fake-for-test-only")
        with pytest.raises(BenchmarkConfigurationError):
            _require_real_execution_enabled()

    def test_explicit_true_does_not_raise(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("RUN_LLM_BENCHMARK", "true")
        _require_real_execution_enabled()  # must not raise
