"""AgentBackend: the staged run lifecycle every backend adapter implements.

**FROZEN** at ``CONTRACT_API_VERSION = 1`` (see the package docstring for the
freeze discipline).

The protocol is one staged lifecycle — prepare → (caller runs the process) →
finalize / classify — rather than per-flag argument methods, because the real
invocations could not be represented as independent fragments: Claude's config
mode, access posture, system prompt, and budget flags are coupled; Kimi's
handshake file carries the prompt, the answer pointer, and the generated
read-only agent profile in one atomic staging step.

The library does not run the process itself in v1: the consumer's
orchestration owns spawn/timeout/cancel via :mod:`pontonier.core.runtime` and
feeds the outcome back through ``finalize``/``classify_failure``. That keeps
each bridge's job-worker plumbing untouched while making every
backend-specific decision flow through the adapter.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from pontonier.conventions.envelope import REPAIR_STEPS

if TYPE_CHECKING:
    from contextlib import AbstractAsyncContextManager

    from pontonier.core.runtime import CommandRun


@dataclass(frozen=True)
class RunRequest:
    """Everything a backend needs to stage one model-bearing run.

    ``kind`` is the canonical verb ("consult" | "review_changes" | "delegate").
    ``config_mode``/``access`` are backend-vocabulary strings (e.g. Claude's
    inherit/scoped/safe/bare and toolless/readonly); backends that lack the
    concept ignore them. ``extra_args`` are operator-supplied descriptors
    already vetted against the contract's ExtraArgsPolicy. ``sanitize_aliases``
    are the worktree path aliases used to scrub prose in results and errors.
    ``instructions_append`` is optional caller-supplied instruction text,
    carried verbatim: ``None`` means no caller-supplied text was given, and
    nothing more — a bridge's own instructions or guardrails are its own
    affair. How a bridge normalizes, bounds, frames, and transports the text
    is bridge policy; the library only carries it. It is NOT an
    ``extra_args`` descriptor: that channel is operator-owned. Backends that
    lack the concept ignore it, like ``config_mode``/``access``.
    """

    kind: str
    prompt: str
    cwd: str
    timeout_seconds: int
    schema: dict[str, Any] | None = None
    model: str | None = None
    reasoning_effort: str | None = None
    budget_usd: float | None = None
    config_mode: str | None = None
    access: str | None = None
    isolation: str | None = None
    extra_args: tuple[str, ...] = ()
    sanitize_aliases: tuple[str, ...] = ()
    instructions_append: str | None = None


@dataclass(frozen=True)
class PreparedRun:
    """A staged invocation: what to spawn and how, plus the artifacts staged for
    it. Yielded by ``prepare``'s context manager; the artifacts are guaranteed
    cleaned up when the context exits, however the run ended."""

    argv: tuple[str, ...]
    env: dict[str, str]
    cwd: str
    stdin_text: str | None = None
    orphan_marker: str | None = None  # passed to runtime.run_async when the contract needs it
    artifacts: tuple[str, ...] = ()  # staged temp paths (handshake, agent file, schema, output)
    # Help-gated flags the preparation DROPPED because the installed CLI does not
    # advertise them. A freeze-window finding from the Codex adapter: production
    # surfaces these as compat warnings and uses them to reconcile reported
    # provenance (a dropped --model means the run used the CLI's default, not the
    # requested slug), so a prepare() that silently discards them cannot carry the
    # real orchestration path. Empty for backends that gate nothing.
    dropped_flags: tuple[str, ...] = ()
    # NAMED staged paths, keyed by the same artifact names `RunOutcome.artifact_texts`
    # uses ("last-message", "answer", "agent", ...). A freeze-window finding from the
    # Kimi adapter: the flat `artifacts` tuple cannot tell the consumer WHICH staged
    # file is the answer channel, and the consumer must read it back inside the
    # prepare() context (staging is torn down on exit) to build `artifact_texts`.
    # When both fields are set they must agree: `artifacts` enumerates exactly the
    # values here (it remains the cleanup/enumeration view).
    artifact_paths: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class RunOutcome:
    """What actually happened: the raw process result plus the artifacts as the
    process left them.

    ``events`` is the backend's raw event payload (e.g. a JSONL stream), kept
    OPAQUE deliberately: real adapters parse it tolerantly with their own
    normalize layers, where a malformed line must degrade rather than raise
    (0.3.0 finding from the Codex adapter — typed event dicts forced eager
    parsing upstream of the tolerance boundary). A backend whose answer and
    metadata all live in stdout (Claude) or in artifacts may leave both
    ``events`` and ``artifact_texts`` empty — using neither channel is a valid
    shape, not a gap."""

    run: CommandRun
    events: str = ""
    artifact_texts: dict[str, str] = field(default_factory=dict)  # name -> contents read back


@dataclass(frozen=True)
class Usage:
    """Token and cost accounting as the backend reported it; every field is None
    when the backend did not report that figure.

    ``cached_input_tokens`` (0.9.0) is the prompt-token count served from the
    provider's cache (Codex and Kimi ``cached_input_tokens``, Claude
    ``cache_read_input_tokens``); ``cache_creation_input_tokens`` (0.9.0) is the
    count written into the cache (Claude only). Both are defaulted and appended,
    so every existing positional ``Usage(input, output, total, cost)`` call keeps
    its meaning.
    """

    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    cost_usd: float | None = None
    cached_input_tokens: int | None = None
    cache_creation_input_tokens: int | None = None


@dataclass(frozen=True)
class ExecResult:
    """The normalized result of a successful run — the protocol's currency.

    ``answer`` is the model's final text. ``structured`` is the parsed
    structured-output object when the request carried a schema and parsing
    succeeded (parse tolerantly; never assume). ``usage`` is None when the
    backend emits no usage events for this mode. ``session_id`` is opportunistic
    metadata, not a resume promise.
    """

    answer: str
    structured: dict[str, Any] | None = None
    usage: Usage | None = None
    session_id: str | None = None
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class RepairHint:
    """One corrective next action, in the shape the bridges' error envelopes already
    use: ``next_step`` is a symbol from ``conventions.envelope.REPAIR_STEPS``,
    ``tool``/``arguments`` name the single callable repair when one exists,
    ``alternative`` is optional prose for a human or agent when the primary call
    does not fit. A consumer serializes it into its own envelope (0.9.0, #24).

    ``next_step`` is validated exactly as ``RepairRule`` validates it, so this
    package owns ONE repair vocabulary and a consumer's serializer maps every
    symbol it can meet. A backend whose native envelope speaks a different step
    vocabulary (claude-in-codex's ``call_tool`` / ``retry_with_changes`` are
    action kinds, not repairs) maps into the shared symbol before building the
    hint; a symbol the shared set lacks is added to ``REPAIR_STEPS``, not
    invented here."""

    next_step: str
    tool: str | None = None
    arguments: dict[str, Any] | None = None
    alternative: str | None = None

    def __post_init__(self) -> None:
        if self.next_step not in REPAIR_STEPS:
            raise ValueError(f"unknown repair step {self.next_step!r}")


@dataclass(frozen=True)
class ClassifiedFailure:
    """A failure mapped into the shared taxonomy (see conventions.envelope).

    ``code`` is a taxonomy code. ``detail`` is sanitized, redacted prose safe
    for the wire. ``retry_after_ms`` is set only for temporary failures that
    declared a delay.

    ``retryable``, ``details`` and ``repair`` (0.9.0, #24) let a backend that
    already computes them hand them to a generic consumer; ``None`` on any of
    them means the backend expressed no opinion and the consumer applies its own
    defaults — it is never a claim. A non-``None`` ``retryable`` overrides the
    ``temporary`` flag of the code's ``RepairRule``: the rule is the default for
    the code, and the backend saw the actual run (``timeout`` is temporary by
    rule, but Claude's is not retryable because a replay may double-charge).
    The shared skeleton in ``classify`` leaves all three ``None``. ``details``
    is the envelope's field-detail object (``{field, value, reason}``), redacted
    by the backend before it lands here.

    ``usage`` (0.9.0) carries whatever accounting the backend could still
    extract from a failed run — Claude's zero-exit error envelope reports
    ``total_cost_usd`` beside ``is_error`` — so a consumer that short-circuits
    to its error path keeps the spend it observed. ``None`` means no
    accounting was recoverable, not that the run was free.
    """

    code: str
    detail: str
    retry_after_ms: int | None = None
    retryable: bool | None = None
    details: dict[str, Any] | None = None
    repair: RepairHint | None = None
    usage: Usage | None = None


@runtime_checkable
class AgentBackend(Protocol):
    """The behavior half of a backend adapter (static facts live on the
    BackendContract). Frozen at contract API 1 — see module docstring."""

    def validate_request(self, request: RunRequest) -> ClassifiedFailure | None:
        """Pre-spend local validation. MUST reject what the upstream CLI would
        silently ignore (the contract's ``effort_silently_ignored_upstream``
        flag makes that obligatory for effort). None means "safe to spend"."""
        ...

    def prepare(self, request: RunRequest) -> AbstractAsyncContextManager[PreparedRun]:
        """Stage one invocation: argv, env, stdin, and any file artifacts
        (handshake, agent profile, schema/output temp files). The context
        manager owns artifact cleanup on exit."""
        ...

    def finalize(self, outcome: RunOutcome, request: RunRequest) -> ExecResult:
        """Extract the answer (last-message file / event stream / stdout
        envelope), parse structured output per the contract's strategy, and pull
        usage/session metadata. Raises nothing for model-quality problems —
        callers branch on the ExecResult; raise only for programming errors."""
        ...

    def classify_failure(self, outcome: RunOutcome, request: RunRequest) -> ClassifiedFailure:
        """Map a failed run into the shared taxonomy using the contract's
        signature tables plus any backend-specific evidence (e.g. Claude's
        stdout JSON envelope)."""
        ...

    def list_models(self) -> tuple[str, ...]:
        """Model identifiers per the contract's catalog strategy. May probe
        (free) for live catalogs; must not spend."""
        ...

    def auth_probe(self) -> bool | None:
        """True/False when auth state is known; None when the probe could not
        answer (map to ``{id}_auth_indeterminate``, never to a login hint)."""
        ...

    def scrub_env(self, env: dict[str, str], config_mode: str | None) -> dict[str, str]:
        """The subprocess environment for a run: connector suppression, secret
        scrubbing per config mode, or a pass-through for backends needing
        neither."""
        ...


@runtime_checkable
class OutcomeInspector(Protocol):
    """OPTIONAL capability (0.9.0): a backend whose process can exit 0 and still
    have failed — Claude's CLI reports errors inside a zero-exit JSON envelope —
    implements this so a generic consumer can learn that before ``finalize``.

    The consumer calls :func:`inspect_outcome` on EVERY completed process,
    whatever its exit status, and treats a returned failure exactly like one
    from ``classify_failure``. Implementations must tolerate any stdout (empty,
    not JSON, truncated) and never raise; returning a ``ClassifiedFailure`` for
    an outcome the backend cannot read is fine, and is what the conformance
    kit accepts. ``None`` means the outcome revealed nothing beyond its exit
    status.

    A failure it returns may carry ``usage`` so the consumer keeps the spend
    recorded in the same envelope that reported the error.

    A backend without the capability is unaffected: the base
    ``AgentBackend`` protocol did not grow.
    """

    def inspect_outcome(self, outcome: RunOutcome, request: RunRequest) -> ClassifiedFailure | None:
        """Return a failure the exit status could not reveal, else ``None``."""
        ...


def inspect_outcome(
    backend: object, outcome: RunOutcome, request: RunRequest
) -> ClassifiedFailure | None:
    """Run the backend's :class:`OutcomeInspector` if it has one.

    Returns ``None`` for a backend without the capability. Deliberately does
    not look at the exit status: which processes get inspected is the
    consumer's rule ("every completed one"), not this helper's.

    Dispatch is structural presence only: ``isinstance`` checks that an
    attribute named ``inspect_outcome`` exists, not that it is callable with
    this arity; ``testing.conformance.check_backend`` reports a backend that
    raises here. The helper shares the Protocol method's name on purpose (one
    vocabulary), which sets one trap: inside an adapter's own
    ``inspect_outcome`` method the bare name resolves to THIS function, so an
    adapter must never call ``inspect_outcome(self, ...)`` from that method —
    it recurses.
    """
    if isinstance(backend, OutcomeInspector):
        return backend.inspect_outcome(outcome, request)
    return None
