# Prompt Version History

**File this document tracks:** `backend/prompts/parser_prompt.txt`
**Current version:** 1.1.0
**Companion config:** `backend/prompts/prompt_config.yaml`
(`prompt_version` there must always match the version at the top of
this changelog -- see "Compatibility" below for what to do if they
disagree.)

## Why this file exists

`parser_prompt.txt` is production software, not a scratch note --
every worked example inside it and every rule it states is something
the future Language Agent (Phase 3.4) and every evaluation dataset
under `datasets/language/` will depend on behaving consistently. A
prompt that changes silently between runs makes benchmark results
(Phase 3.6) impossible to compare and makes a regression impossible to
bisect. This document is the changelog that makes prompt changes
reviewable and attributable the same way a code changelog would be --
see `backend/prompts/README.md` for how the prompt asset package fits
together and how a change to `parser_prompt.txt` should be reviewed
before it earns a new entry here.

## Versioning policy

This file follows semantic versioning, applied to the prompt's own
contract (not the Task schema's -- see
`backend/schemas/metadata.py`'s `SCHEMA_VERSION` for that, and
`prompt_config.yaml`'s "Versioning" section for how the two relate):

- **MAJOR** -- a change that alters the JSON contract itself: a field
  renamed, removed, or given new required semantics. Always paired
  with a MAJOR bump to `SCHEMA_VERSION`, since the two files describe
  two halves of one contract.
- **MINOR** -- an additive, backward-compatible change: a new
  preferred goal added to the catalog, a new worked example, a new
  optional field the prompt now populates (only once that field
  already exists on the schema with a safe default).
- **PATCH** -- a wording clarification, typo fix, or comment-only
  change that does not alter model behavior in any way a downstream
  consumer could observe.

## Version History

### 1.1.0 -- Phase 3.3 (current)

**Type:** Minor (additive, backward-compatible)

**Changes:**
- Added the **SUPPORTED GOALS** section: a preferred, categorized
  vocabulary of goal verb phrases (navigation, manipulation,
  perception, state change, control), explicitly documented as an open
  vocabulary rather than a closed enum -- consistent with
  `schemas.task.Task.goal`'s validator, which checks snake_case
  formatting only, never membership in a fixed list. Added to reduce
  goal-phrasing drift across repeated calls (e.g. "go_get" vs "fetch"
  for the same intent), which matters for evaluation reproducibility
  once Phase 3.6 exists.
- Added the **EXTENSION GUIDANCE** section: documents how future prompt
  changes should be classified (major/minor/patch), the rule that a
  schema change must land before the prompt is asked to emit a new
  field, and points to `datasets/language/` as where example volume
  should grow instead of this file.
- No existing field, rule, or example from 1.0.0 was altered or
  removed -- every 1.0.0 output shape remains valid under 1.1.0.

**Compatibility:** Fully backward-compatible with 1.0.0. Any consumer
built against 1.0.0's output shape continues to work unmodified.

### 1.0.0 -- Phase 3.1 (initial release)

**Type:** Major (initial contract)

**Changes:**
- Initial production system prompt: assistant role, JSON-only output
  contract, core principles (preserve intent, never invent objects or
  locations, missing information -> `null`, ambiguity ->
  `needs_clarification`), single-task vs. multi-task handling, full
  field definitions matching `schemas.task.Task` /
  `schemas.task.SingleTask` / `schemas.task.MultiTask`, and five worked
  examples (fully-specified single task, missing-information handling,
  ambiguity handling, multi-task sequencing, constraint + priority
  extraction).

**Compatibility:** N/A (initial version).

## Known Issues

- **No closed goal vocabulary enforcement.** Because `goal` is
  validated only for snake_case formatting (not list membership), two
  different LLM providers could legitimately choose different but
  equally valid phrasings for the same intent (e.g. "fetch" vs.
  "retrieve"). The SUPPORTED GOALS catalog (1.1.0) reduces but does not
  eliminate this -- a model may still ignore the preference list.
  Tracked for measurement once Phase 3.6's benchmarking exists;
  resolving it further (e.g. a canonicalization/repair step) belongs to
  Phase 3.5 (Output Validation & Error Recovery), not this prompt.
- **`estimated_goal` phrasing is not deterministic across models.**
  Different models will phrase the same success state differently
  (e.g. "the mug is on the table" vs. "the mug ends up on the table"),
  which is expected free text, not a bug, but means
  `estimated_goal` cannot be evaluated with exact-string matching --
  `datasets/language/evaluation/success_cases.json` scores it
  qualitatively rather than by exact match.
- **No formal handling of instructions that require world knowledge
  the robot doesn't have** (e.g. "put it where it usually goes"). The
  current prompt correctly flags these as needing clarification (see
  `datasets/language/prompts/edge_cases.json`), but this has not yet
  been stress-tested against a wide range of such phrasings.

## Future Improvements

- Expand the SUPPORTED GOALS catalog based on real benchmark data
  (Phase 3.6) showing which goals models actually produce for a given
  category of instruction, rather than purely anticipated categories.
- Consider a provider-specific prompt variant if Phase 3.6 benchmarking
  (across GPT, Qwen, Llama, Phi) shows one model family consistently
  needs different phrasing to hit the same accuracy -- would become
  version `2.0.0` territory only if it changed the contract itself;
  a provider-specific wording variant that preserves the same contract
  would stay MINOR.
- A multilingual variant is plausible future work once the project
  scope extends past English instructions (see
  `backend/docs/language_interface_spec.md` section 20, "Assumptions").

## Compatibility

`prompt_config.yaml`'s `prompt_version` field must always equal the
version at the top of this document. If they ever disagree, this
document is authoritative -- `prompt_config.yaml` should be corrected
to match, not the other way around, since this file is the reviewed
changelog and `prompt_config.yaml` is a point-in-time configuration
snapshot (see `prompt_config.yaml`'s own "Configuration notes"
section).

`schema_version` in `prompt_config.yaml` records which
`schemas.metadata.SCHEMA_VERSION` this prompt version was authored
against. Prompt version 1.1.0 targets schema version 1.0.0 -- no
schema change has been required by any prompt change so far, since
every prompt revision to date has been additive within the existing
field set.
