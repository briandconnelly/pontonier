"""``check_backend`` and the OutcomeInspector capability: an inspector runs on EVERY
completed process, including ones whose stdout is empty or not JSON, so one that raises
there turns a classifiable run into a consumer crash. The probe feeds three hostile
stdouts and reports a raise or a wrong return type as a violation. Backends without the
capability are untouched (issue #15 is about a self-disabling check; this one has no
contract flag to disable it)."""

from __future__ import annotations

import json

from pontonier.backend.protocol import ClassifiedFailure, RunOutcome, RunRequest
from pontonier.testing import conformance
from test_conformance_fakes import CLAUDE_CONTRACT, ClaudeLikeBackend


class TolerantInspector(ClaudeLikeBackend):
    def inspect_outcome(self, outcome: RunOutcome, request: RunRequest) -> ClassifiedFailure | None:
        try:
            envelope = json.loads(outcome.run.stdout)
        except json.JSONDecodeError:
            return None
        if isinstance(envelope, dict) and envelope.get("is_error"):
            return ClassifiedFailure(code="nonzero_exit", detail="error envelope")
        return None


class RaisingInspector(ClaudeLikeBackend):
    def inspect_outcome(self, outcome: RunOutcome, request: RunRequest) -> ClassifiedFailure | None:
        return json.loads(outcome.run.stdout).get("is_error") and ClassifiedFailure(
            code="nonzero_exit", detail="error envelope"
        )


class WrongTypeInspector(ClaudeLikeBackend):
    def inspect_outcome(self, outcome: RunOutcome, request: RunRequest):  # type: ignore[override]
        return "not a ClassifiedFailure"


def test_backend_without_the_capability_is_unaffected():
    assert conformance.check_backend(CLAUDE_CONTRACT, ClaudeLikeBackend()) == []


def test_tolerant_inspector_is_clean():
    assert conformance.check_backend(CLAUDE_CONTRACT, TolerantInspector()) == []


def test_raising_inspector_is_a_violation():
    violations = conformance.check_backend(CLAUDE_CONTRACT, RaisingInspector())
    assert violations, "the probe must catch an inspector that raises on non-JSON stdout"
    assert all(v.startswith("inspect_outcome raised") for v in violations)
    assert any("JSONDecodeError" in v for v in violations)


def test_wrong_return_type_is_a_violation():
    violations = conformance.check_backend(CLAUDE_CONTRACT, WrongTypeInspector())
    assert violations
    assert all(v.startswith("inspect_outcome returned") for v in violations)
