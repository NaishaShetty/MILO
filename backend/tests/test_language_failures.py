"""
test_language_failures.py

Purpose
-------
Verifies `language.failures`'s closed taxonomy and retry-policy lookup:
that every documented `FailureCategory` exists, that
`is_retryable()` matches the Phase 3.5 "Retry Strategy" policy this
project's requirements document exactly (which categories are worth a
fresh attempt vs. a hard stop), and that `RuntimeMetadata`/
`FailureRecord` behave as plain, inspectable data.
"""

from __future__ import annotations

from language.failures import (
    FailureCategory,
    FailureRecord,
    RuntimeMetadata,
    is_retryable,
)


class TestFailureCategoryTaxonomy:
    def test_every_required_category_exists(self) -> None:
        required = {
            "INVALID_JSON",
            "EMPTY_RESPONSE",
            "SCHEMA_VALIDATION_ERROR",
            "SEMANTIC_VALIDATION_ERROR",
            "AMBIGUOUS_COMMAND",
            "LLM_TIMEOUT",
            "LLM_PROVIDER_ERROR",
            "LLM_CONFIGURATION_ERROR",
            "RETRY_EXHAUSTED",
            "UNSUPPORTED_RESPONSE",
            "SAFE_REPAIR_FAILED",
        }
        actual = {member.name for member in FailureCategory}
        assert required <= actual

    def test_categories_are_string_enum_members(self) -> None:
        # Matches this project's convention (schemas/enums.py) so a
        # category serializes as a plain string and compares equal to
        # one -- important for future logging/benchmarking consumers.
        assert FailureCategory.INVALID_JSON == "invalid_json"
        assert isinstance(FailureCategory.INVALID_JSON, str)


class TestRetryPolicyLookup:
    def test_retryable_categories(self) -> None:
        for category in (
            FailureCategory.INVALID_JSON,
            FailureCategory.EMPTY_RESPONSE,
            FailureCategory.SCHEMA_VALIDATION_ERROR,
            FailureCategory.SEMANTIC_VALIDATION_ERROR,
            FailureCategory.LLM_TIMEOUT,
            FailureCategory.LLM_PROVIDER_ERROR,
            FailureCategory.UNSUPPORTED_RESPONSE,
        ):
            assert is_retryable(category) is True

    def test_non_retryable_categories(self) -> None:
        for category in (
            FailureCategory.LLM_CONFIGURATION_ERROR,
            FailureCategory.RETRY_EXHAUSTED,
            FailureCategory.AMBIGUOUS_COMMAND,
            FailureCategory.SAFE_REPAIR_FAILED,
        ):
            assert is_retryable(category) is False


class TestStructuredMetadata:
    def test_runtime_metadata_is_a_plain_frozen_record(self) -> None:
        metadata = RuntimeMetadata(
            provider="openai",
            model="gpt-4o-mini",
            prompt_version="1.1.0",
            schema_version="1.0.0",
            attempt_number=2,
            latency_ms=123.4,
            recovered=True,
            last_failure=FailureCategory.INVALID_JSON,
        )
        assert metadata.attempt_number == 2
        assert metadata.recovered is True
        assert metadata.last_failure == FailureCategory.INVALID_JSON

    def test_failure_record_carries_no_credential_by_construction(self) -> None:
        # This module never assembles error text itself -- a
        # `FailureRecord.message` is always whatever the upstream
        # component already redacted (see this module's Security
        # note). This test only asserts the shape is inspectable, not
        # that redaction happened here (that's covered in
        # test_language_llm_client.py / test_language_gemini_client.py).
        record = FailureRecord(
            category=FailureCategory.LLM_TIMEOUT,
            stage="llm_call",
            message="LLM request timed out after 30.0s",
            retryable=True,
            attempt_number=1,
        )
        assert record.category == FailureCategory.LLM_TIMEOUT
        assert record.retryable is True
