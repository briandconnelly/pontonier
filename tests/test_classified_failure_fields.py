"""``ClassifiedFailure.retryable`` / ``details`` / ``repair`` (#24; background
briandconnelly/claude-in-codex#145): defaulted machine
fields so an adapter that already computes them (Claude's ``ErrorInfo`` carries repair,
details and retryable) can hand them to a generic consumer instead of dropping them.
``None`` on any of them means "the backend expressed no opinion; apply your defaults" —
it is never a claim. The shared classifier leaves all three None."""

from __future__ import annotations

import dataclasses

import pytest

from conftest import make_run
from pontonier.backend import CONTRACT_API_VERSION, classify
from pontonier.backend.protocol import (
    ClassifiedFailure,
    RepairHint,
    RunOutcome,
    RunRequest,
    Usage,
)
from test_contract import make_contract

CONTRACT = make_contract()
REQUEST = RunRequest(kind="consult", prompt="q", cwd=".", timeout_seconds=10)


def test_new_fields_default_to_none_and_keep_the_freeze():
    failure = ClassifiedFailure(code="timeout", detail="d")
    assert failure.retryable is None
    assert failure.details is None
    assert failure.repair is None
    assert failure.usage is None
    assert CONTRACT_API_VERSION == 1


def test_positional_construction_is_unchanged():
    failure = ClassifiedFailure("nonzero_exit", "d", 250)
    assert (failure.code, failure.detail, failure.retry_after_ms) == ("nonzero_exit", "d", 250)
    names = [f.name for f in dataclasses.fields(ClassifiedFailure)]
    assert names == [
        "code",
        "detail",
        "retry_after_ms",
        "retryable",
        "details",
        "repair",
        "usage",
    ]


def test_repair_hint_is_a_frozen_next_action():
    hint = RepairHint(next_step="run_status")
    assert (hint.tool, hint.arguments, hint.alternative) == (None, None, None)
    full = RepairHint(
        next_step="run_status",
        tool="amicus_backends",
        arguments={"backend": "claude"},
        alternative="Run `claude /login` and retry.",
    )
    assert full.arguments == {"backend": "claude"}
    with pytest.raises(dataclasses.FrozenInstanceError):
        full.next_step = "other"  # type: ignore[misc]


def test_shared_classifier_expresses_no_opinion():
    outcome = RunOutcome(run=make_run(stderr="boom", exit_code=1))
    failure = classify.classify(CONTRACT, outcome, REQUEST, detail="detail")
    assert failure.code == "nonzero_exit"
    assert (failure.retryable, failure.details, failure.repair) == (None, None, None)


def test_backend_hook_result_passes_through_untouched():
    # A backend that knows more (Claude's timeout is NOT retryable because a replay may
    # double-charge) returns a populated failure; the skeleton must not strip it.
    populated = ClassifiedFailure(
        code="timeout",
        detail="deadline",
        retryable=False,
        details={"field": "timeout_seconds", "reason": "exceeded"},
        repair=RepairHint(next_step="raise_timeout", tool="amicus_consult"),
    )
    outcome = RunOutcome(run=make_run(exit_code=1, timed_out=True))
    result = classify.classify(
        CONTRACT, outcome, REQUEST, detail="detail", backend_hook=lambda _o, _r: populated
    )
    assert result is populated


def test_usage_rides_a_failure():
    # A zero-exit error envelope still reports what the run cost; the field keeps it.
    failure = ClassifiedFailure(code="nonzero_exit", detail="d", usage=Usage(cost_usd=0.42))
    assert failure.usage is not None
    assert failure.usage.cost_usd == 0.42
