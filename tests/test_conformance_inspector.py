"""``check_backend`` and the OutcomeInspector capability: an inspector runs on EVERY
completed process, including ones whose stdout is empty or not JSON, so one that raises
there turns a classifiable run into a consumer crash. The probe feeds four hostile
outcomes and reports a raise or a wrong return type as a violation. Backends without the
capability are untouched (issue #15 is about a self-disabling check; this one has no
contract flag to disable it)."""

from __future__ import annotations

import json

from pontonier.backend.protocol import ClassifiedFailure, RunOutcome, RunRequest
from pontonier.core.runtime import TIMED_OUT
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


class TimeoutBranchRaisingInspector(ClaudeLikeBackend):
    """Tolerant everywhere except the timeout branch a real inspector has, which keys
    on the sentinel ``run_async`` writes into stderr. The probe must present that
    sentinel, or this raise passes conformance clean."""

    def inspect_outcome(self, outcome: RunOutcome, request: RunRequest) -> ClassifiedFailure | None:
        if outcome.run.stderr == TIMED_OUT or outcome.run.exit_code == -9:
            raise RuntimeError("no envelope to read after a timeout")
        return None


class WrongTypeInspector(ClaudeLikeBackend):
    def inspect_outcome(self, outcome: RunOutcome, request: RunRequest):  # type: ignore[override]
        return "not a ClassifiedFailure"


class AlwaysFailsInspector(ClaudeLikeBackend):
    """The realistic shape: anything that is not a clean envelope is a failure."""

    def inspect_outcome(self, outcome: RunOutcome, request: RunRequest) -> ClassifiedFailure | None:
        return ClassifiedFailure(code="nonzero_exit", detail="not a clean envelope")


def test_backend_without_the_capability_is_unaffected():
    assert conformance.check_backend(CLAUDE_CONTRACT, ClaudeLikeBackend()) == []


def test_tolerant_inspector_is_clean():
    assert conformance.check_backend(CLAUDE_CONTRACT, TolerantInspector()) == []


def test_raising_inspector_is_a_violation():
    violations = conformance.check_backend(CLAUDE_CONTRACT, RaisingInspector())
    assert violations, "the probe must catch an inspector that raises on non-JSON stdout"
    assert all(v.startswith("inspect_outcome raised") for v in violations)
    assert any("JSONDecodeError" in v for v in violations)
    assert len(violations) == 4
    assert any("timed out" in v for v in violations)


def test_timed_out_probe_has_the_shape_run_async_returns():
    violations = conformance.check_backend(CLAUDE_CONTRACT, TimeoutBranchRaisingInspector())
    assert len(violations) == 1
    assert "RuntimeError" in violations[0]
    assert "timed out" in violations[0]


def test_wrong_return_type_is_a_violation():
    violations = conformance.check_backend(CLAUDE_CONTRACT, WrongTypeInspector())
    assert violations
    assert all(v.startswith("inspect_outcome returned") for v in violations)
    assert len(violations) == 4


def test_inspector_that_returns_a_failure_for_everything_is_clean():
    # Tolerance is the invariant, not accuracy: returning a ClassifiedFailure for
    # empty, malformed and timed-out outcomes is exactly what the probe accepts.
    assert conformance.check_backend(CLAUDE_CONTRACT, AlwaysFailsInspector()) == []
