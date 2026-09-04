"""``OutcomeInspector`` (0.9.0): an OPTIONAL capability a backend adds when a process
that exited 0 can still be a failure. Claude's CLI reports errors in a zero-exit JSON
envelope (``is_error`` / a non-success ``subtype``), so a consumer that branches on exit
status alone reports those as successful empty answers. The consumer calls
``inspect_outcome`` on EVERY completed process before ``finalize``; a backend without the
capability yields None and nothing changes for it. The base ``AgentBackend`` protocol does
not grow, which is what keeps this inside the freeze."""

from __future__ import annotations

import json

from conftest import make_run
from pontonier.backend import CONTRACT_API_VERSION
from pontonier.backend.protocol import (
    AgentBackend,
    ClassifiedFailure,
    OutcomeInspector,
    RunOutcome,
    RunRequest,
    inspect_outcome,
)
from test_conformance_fakes import ClaudeLikeBackend, CodexLikeBackend

REQUEST = RunRequest(kind="consult", prompt="q", cwd=".", timeout_seconds=10)


class EnvelopeInspectingBackend(ClaudeLikeBackend):
    """ClaudeLike plus the capability: a zero-exit envelope with is_error is a failure."""

    def inspect_outcome(self, outcome: RunOutcome, request: RunRequest) -> ClassifiedFailure | None:
        try:
            envelope = json.loads(outcome.run.stdout)
        except json.JSONDecodeError:
            return ClassifiedFailure(code="invalid_json", detail="stdout was not a JSON envelope")
        if envelope.get("is_error"):
            return ClassifiedFailure(
                code="nonzero_exit",
                detail=str(envelope.get("result", ""))[:80],
                retryable=False,
            )
        return None


def test_backend_without_the_capability_yields_none_and_the_freeze_holds():
    backend = CodexLikeBackend()
    assert not isinstance(backend, OutcomeInspector)
    assert isinstance(backend, AgentBackend)  # the base protocol did not grow
    outcome = RunOutcome(run=make_run(stdout="anything", exit_code=0))
    assert inspect_outcome(backend, outcome, REQUEST) is None
    assert CONTRACT_API_VERSION == 1


def test_inspector_is_detected_structurally():
    backend = EnvelopeInspectingBackend()
    assert isinstance(backend, OutcomeInspector)
    assert isinstance(backend, AgentBackend)


def test_inspector_flags_a_zero_exit_error_envelope():
    backend = EnvelopeInspectingBackend()
    stdout = json.dumps({"is_error": True, "result": "budget exceeded"})
    outcome = RunOutcome(run=make_run(stdout=stdout, exit_code=0))
    failure = inspect_outcome(backend, outcome, REQUEST)
    assert failure is not None
    assert failure.code == "nonzero_exit"
    assert failure.detail == "budget exceeded"
    assert failure.retryable is False


def test_inspector_passes_a_clean_envelope():
    backend = EnvelopeInspectingBackend()
    stdout = json.dumps({"result": "ok", "subtype": "success"})
    outcome = RunOutcome(run=make_run(stdout=stdout, exit_code=0))
    assert inspect_outcome(backend, outcome, REQUEST) is None


def test_helper_does_not_prefilter_on_exit_status():
    # The consumer's rule is "inspect every completed process"; the helper must not
    # decide for it, so a nonzero exit still reaches the inspector.
    backend = EnvelopeInspectingBackend()
    outcome = RunOutcome(run=make_run(stdout="not json", exit_code=2))
    failure = inspect_outcome(backend, outcome, REQUEST)
    assert failure is not None
    assert failure.code == "invalid_json"
