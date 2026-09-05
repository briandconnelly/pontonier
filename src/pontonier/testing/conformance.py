"""Adapter conformance: does a backend implementation honor its contract?

Structural conformance (``isinstance(backend, AgentBackend)``) only proves the
members exist; these checks probe the INVARIANTS that made the protocol
necessary. Each returns violation strings (empty = pass).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pontonier.backend.protocol import (
    AgentBackend,
    ClassifiedFailure,
    OutcomeInspector,
    RunOutcome,
    RunRequest,
)
from pontonier.core.runtime import TIMED_OUT, CommandRun
from pontonier.testing.surface_honesty import find_contract_self_contradictions

if TYPE_CHECKING:
    from pontonier.backend.contract import BackendContract


def check_contract(contract: BackendContract) -> list[str]:
    """Static invariants a contract must satisfy on its own."""
    out: list[str] = []
    out.extend(
        find_contract_self_contradictions(
            contract.forbidden_surface_phrases,
            {
                "readonly_honesty_statement": contract.readonly_honesty_statement,
                "implicit_context_disclosure": contract.implicit_context_disclosure,
            },
        )
    )
    overlap = set(contract.always_send_flags) & set(contract.help_gated_flags)
    if overlap:
        out.append(
            f"flags {sorted(overlap)} are both always-send and help-gated; a flag has "
            "exactly one gating class"
        )
    if (
        contract.limits.max_argv_prompt_chars is not None
        and contract.limits.max_argv_prompt_chars <= 0
    ):
        out.append("max_argv_prompt_chars must be positive when set")
    if "usage_accounting" in contract.supported_features and not contract.usage_event_markers:
        out.append(
            "contract declares usage_accounting but lists no usage_event_markers to extract it from"
        )
    return out


def check_backend(contract: BackendContract, backend: object) -> list[str]:
    """Behavioral invariants, probed without spawning the real CLI. The backend
    under test may be the real adapter with its subprocess seams stubbed, or a
    fake standing in for one during protocol development."""
    out: list[str] = []
    if not isinstance(backend, AgentBackend):
        out.append("backend does not structurally implement AgentBackend")
        return out

    if contract.effort_silently_ignored_upstream:
        # The upstream CLI accepts a bad effort and exits 0, so spend-side
        # validation is the ONLY protection. An adapter that lets a bogus effort
        # through will burn money and silently produce a default-effort answer.
        bogus = RunRequest(
            kind="consult",
            prompt="conformance probe",
            cwd=".",
            timeout_seconds=1,
            reasoning_effort="not-a-real-effort-level",
        )
        if backend.validate_request(bogus) is None:
            out.append(
                "contract says effort is silently ignored upstream, but "
                "validate_request accepted a bogus reasoning_effort — pre-spend "
                "validation is mandatory for this backend"
            )

    if isinstance(backend, OutcomeInspector):
        # The inspector runs on EVERY completed process, including ones whose
        # stdout is empty or not JSON. One that raises there turns a classifiable
        # run into a consumer crash, so tolerance is the invariant, not accuracy.
        probe = RunRequest(kind="consult", prompt="conformance probe", cwd=".", timeout_seconds=1)
        # Each outcome carries nothing but the process result — no events, no
        # artifact_texts — because that is what a consumer has when the process
        # never produced them. Returning a ClassifiedFailure for these is fine;
        # raising is the violation.
        hostile = (
            RunOutcome(run=CommandRun("", "", 0, 1, False)),
            RunOutcome(run=CommandRun("not json", "", 0, 1, False)),
            RunOutcome(run=CommandRun("{", "", 0, 1, False)),
            # Timed out is still "completed"; this is the shape run_async returns.
            RunOutcome(run=CommandRun("", TIMED_OUT, -9, 1, True)),
        )
        for outcome in hostile:
            label = f"stdout {outcome.run.stdout!r}" + (
                ", timed out" if outcome.run.timed_out else ""
            )
            try:
                result = backend.inspect_outcome(outcome, probe)
            except Exception as exc:
                out.append(
                    f"inspect_outcome raised {type(exc).__name__} on {label}; "
                    "it must return None or a ClassifiedFailure"
                )
                continue
            # Reachable only when a plugin violates its own annotation; a type
            # checker may call this branch unreachable. Keep it — third-party
            # plugins are exactly who this probe exists for.
            if result is not None and not isinstance(result, ClassifiedFailure):
                out.append(
                    f"inspect_outcome returned {type(result).__name__} on {label}; "
                    "it must return None or a ClassifiedFailure"
                )
    return out
