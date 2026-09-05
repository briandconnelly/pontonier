# Changelog

All notable changes to this project will be documented in this file. The format
is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

This file is decision history, not current policy. Rules that still bind live in
[AGENTS.md](AGENTS.md) and the documents it links.

## [Unreleased]

### Added

- `Usage.cached_input_tokens` and `Usage.cache_creation_input_tokens`: defaulted fields for
  the cache accounting every bridge already reports and every adapter's `finalize` dropped.
  **Bridges:** each adapter can now carry the figure; nothing changes until it does.
- `ClassifiedFailure.retryable`, `.details`, `.repair` (with the new `RepairHint`
  dataclass) and `.usage` (so a failure surfaced from a zero-exit error envelope keeps
  its cost) — #24 (background: briandconnelly/claude-in-codex#145). Defaulted; `None`
  means the backend expressed no opinion, never a claim, and a non-`None` `retryable`
  overrides the code's `RepairRule.temporary`. `RepairHint.next_step` is validated
  against `conventions.envelope.REPAIR_STEPS`, the same set `RepairRule` uses, so
  bridges keep one repair vocabulary. The shared classifier leaves all four `None`.
  **Bridges:** `claude-in-codex` can stop documenting its `classify_failure` as lossy.
- `OutcomeInspector`, an optional runtime-checkable capability, and the
  `pontonier.backend.protocol.inspect_outcome` helper: a backend whose process can exit 0
  and still have failed implements it, and a consumer calls the helper on every completed
  process before `finalize`. `AgentBackend` is unchanged and `CONTRACT_API_VERSION`
  stays 1.
- `testing.conformance.check_backend` probes an `OutcomeInspector` with empty, non-JSON,
  truncated and timed-out outcomes (the last in the shape `run_async` returns) and
  reports a raise or a wrong return type as a violation.
- `scripts/check_consumers.sh`: runs each consuming bridge's suite against this tree's
  built wheel, asserting each suite imports that exact build while its other locked
  dependencies stay untouched. Manual for now; the release procedure runs it before a
  release PR.

All four protocol additions exist for `amicus`, the unified multi-backend server that
replaces the three bridges; its design spec records why each is needed.

## [0.8.0] — 2026-08-31

### Added

- `CommandRun.capture_failed` (#18): a defaulted field set when a capture thread died, so
  an empty stdout is distinguishable from output that was lost. `errors="replace"` removes
  the one known cause, but not the shape it produced — a daemon pump thread's exception is
  printed by `threading.excepthook` and then discarded, so *any* future failure in a pump
  would again surface as a clean `exit_code=0` with empty output. The pumps now record it
  and log at ERROR. Distinct from `output_truncated`, which means the byte cap was reached
  and the capture is deliberately bounded. Defaulted, so every positional construction and
  every caller that ignores it is unaffected; `run_sync_capture` has no pumps and always
  reports `False`.

### Fixed

- `runtime.run_sync_capture` now classifies every spawn failure as `binary_missing`
  instead of raising (#16). It caught only `FileNotFoundError` and `NotADirectoryError`,
  and wrapped the whole `subprocess.run` lifecycle in that one `try`, so a binary that is
  present but cannot be executed — a directory with the binary's name on `PATH`, a file
  without the execute bit, an ENOEXEC file — escaped as a raised `OSError` from a function
  whose docstring promises a `CommandRun` and the same shape as `run_async`. `run_async`
  already caught `OSError` around `Popen` alone and classified all of them. The in-repo
  caller broke on the same edge: `preflight.HelpProbe.flag_support` promises to fail open
  and instead propagated the `PermissionError`.

  The fix isolates the spawn from the drain, rather than widening the existing `except`:
  the single `try` covered both phases, so nothing inside or outside the function could
  tell a failed exec from a failed pipe read, and a widened clause would have reported a
  communicate failure as a missing binary. A communicate-phase error still propagates,
  after the child is killed and its pipes are closed — dropping `subprocess.run` means
  reproducing the cleanup its `with Popen(...)` performed on every exit path.

  **Bridges:** `BINARY_NOT_FOUND` marks the whole spawn phase, not only an absent binary —
  it already covered an unusable `cwd` before this change. A bridge that turns
  `binary_missing` into "install the CLI" advice may want to widen that wording.
  `codex-in-claude` can drop the downstream `errno`+`OSError.filename` heuristic it carries
  for this (codex-in-claude#541) once it pins a release containing this fix.

- Undecodable child output no longer breaks a run (#18). Both runners decoded a
  subprocess's streams as strict UTF-8, so one stray byte from a CLI broke each of them
  differently: `run_sync_capture` raised `UnicodeDecodeError`, and `run_async` did not
  raise at all — its stdout pump thread died and the run returned a success-shaped
  `CommandRun` (`exit_code=0`, `timed_out=False`, `output_truncated=False`) with the
  output silently discarded, leaving a caller no field to branch on. Both now decode with
  `errors="replace"`: captured output is diagnostic text, so a U+FFFD is the right loss.
  Not `errors="surrogateescape"`, which `gitproc`/`gitdiff` use deliberately for
  byte-exact git paths — a lone surrogate raises again wherever the text is re-encoded,
  which for a bridge is the JSON response.

  The same strictness broke the orphan sweep. `_ps_matches` reads the command line of
  **every process on the machine**, and documents that it "must never raise into the
  caller's error path", but any unrelated program started with a non-UTF-8 `argv` made it
  raise — breaking teardown for every run, not only the one that owned the stray process.
  It decodes with `errors="surrogateescape"` — deliberately not the replacement used for
  captured output. That text decides which process groups get `SIGKILL`ed, so it needs
  byte identity: replacement collapses every invalid byte to U+FFFD, which makes distinct
  command lines compare equal, and a marker holding a literal U+FFFD would match an
  unrelated process whose `argv` holds a raw `0xff`. This change makes that newly
  reachable, because it is what starts putting U+FFFD in the output a bridge may derive a
  marker from. A lone surrogate cannot leak: nothing but pids leaves that function.
  Whether the raw byte reaches it at all depends on the platform's `ps` — observed passing
  through on macOS and not surfacing on the CI Linux runners — so the exposure varies
  while the fix is unconditional.

  **Bridges:** output that previously arrived empty (or as a raised error from a probe)
  now arrives with U+FFFD in place of undecodable bytes. A bridge asserting on exact
  stdout may see text where it saw `""`.

## [0.7.0] — 2026-08-30

### Added

- `RunRequest.instructions_append` (#12): a defaulted field for caller-supplied text a
  bridge composes into the model's developer/system-level instructions *behind* its own
  framing. Both bridges with a system-prompt/developer-instructions parameter had been
  pressing `RunRequest.extra_args` into service as the carrier (claude-in-codex#130 folds an
  `("--append-system-prompt", text)` pair in `prepare()`; codex-in-claude#556 was about to
  do the same with `-c developer_instructions`), which misstates that channel — the protocol
  defines `extra_args` as operator descriptors vetted by `ExtraArgsPolicy` — and forces a
  dishonest `allowed_option_forms` entry so the conformance kit accepts the adapter's own
  descriptor. The library carries the text verbatim: normalization, the byte cap, the
  forged-marker refusal, the framing prose, and the fingerprint a bridge reports are bridge
  policy, and so is whatever instructions or guardrails a bridge sends on its own — `None`
  means only that no caller-supplied text was given. Adapters that lack the concept ignore
  it, as they do `config_mode`/`access`. A defaulted field is what the v1 freeze permits;
  `CONTRACT_API_VERSION` stays 1. Adoption: codex-in-claude#558, claude-in-codex#132.

## [0.6.0] — 2026-08-20

### Added

- `redaction.sanitize_echo` and `redaction.sanitize_echo_prose`: sanitize foreign text
  bound for an error envelope by deleting every Unicode `Cc` code point *before*
  redacting it. Bridges echo subprocess stderr, config keys, and paths into agent-visible
  errors, where an escape sequence can recolor, reposition, or erase — and where a
  control character wedged into a secret defeats the redactor's patterns outright, so the
  value rides out as plaintext. The order is fixed inside the functions and is not a
  caller's to choose: redacting first leaves the split value untouched, and stripping
  afterwards then reassembles the contiguous secret in the outgoing text. `sanitize_echo`
  is for a single-token span (a config key, a path, a rejected flag name);
  `sanitize_echo_prose` is for a multi-line diagnostic and keeps line feeds only when
  removing them yields exactly the fully collapsed view — so the returned text can never
  show anything collapsing would have hidden. In practice newlines survive in a
  diagnostic the redactor did not touch across a line boundary; once a redaction meets a
  boundary the text collapses, deliberately. Neither truncates — callers disagree about
  both the bound and the direction, so each applies its own, after the call.

  Stripping never discloses more than not stripping. One case would have: deleting a
  control character out of a damaged `-----END … PRIVATE KEY-----` marker terminates a
  block that was failing closed, uncovering everything its blanket redaction covered —
  reachable on purpose by an attacker cancelling a blanket that was protecting someone
  else's secret further down. Both helpers restore the unstripped text's coverage in that
  case. The reverse (a repaired `BEGIN` marker, which redacts more) is left alone.
- `worktree.sanitize_echo_prose`: the same stripping ahead of `sanitize_prose`'s alias
  staging. A control character defeats relativization for the same reason it defeats
  redaction — alias matching is an exact string match — so a corrupted worktree path
  would otherwise ride out into an envelope after the worktree is gone. Stripping the
  *output* of `sanitize_prose` cannot fix that: by then the miss has already happened.

  WHERE the strip goes is the subtle part, and both ends are wrong. Stripping *before* the
  staging destroys alias matching from the other side: `_replace_aliases` needs a delimiter
  beside an alias, and a control character is often the delimiter it has — line feed, tab,
  and carriage return all behave this way, so `"prefix\t<root>/f.py"` came back with the
  absolute path intact. So the strip runs in the one window where neither failure is
  reachable: after staging (aliases sit behind alphanumeric placeholders that deleting
  characters cannot damage) and before redaction. Staging then runs a second time on the
  transformed text, because the two passes catch different aliases and the result is their
  union — the first sees the delimiters the strip is about to delete, the second sees a
  path the strip *repaired*. `sanitize_prose` itself is unchanged: one staging pass, no
  transform, byte-identical.

### Changed

- `redaction.exc_summary` routes its detail through `sanitize_echo_prose` rather than
  bare `redact_text`. Exception text reaching an envelope is echoed foreign text under
  the same rule as any other diagnostic. **Bridges: this changes the content of every
  `exc_summary`-derived error message whose exception text carries a control character** —
  judge your own fingerprint and breaking status by your own repository's rules.

### Repository

- `AGENTS.md` gains a **Bridge intake** section: what this library accepts from a
  consuming bridge, and what stays in the bridge. It states the intake criterion, that
  bridge policy stays downstream, that a mixed change lands in two repositories, that a
  fix a bridge waits for needs a release and not just a merge, that a change to a value
  bridges expose is recorded here so each bridge can judge it, and where each half of a
  change is tested. Previously only the downstream half of that decision was written
  down, in `codex-in-claude`'s `AGENTS.md`; a bridge could read "send it upstream" with
  nothing saying what upstream accepts. The two sections link to each other instead of
  restating each other.
- The repository now carries an instruction layer: `AGENTS.md` (canonical norms,
  with `CLAUDE.md` pointing at it), `CONTRIBUTING.md` (setup, the gate, commit
  format), `docs/releasing.md`, and `docs/github-config.md` for the enforced
  controls. Previously an agent had to infer all of it from CI YAML and git history.
- `scripts/check.sh` is the one verification entry point. `.github/workflows/test.yml`
  runs that exact script, so a green local run is a green CI run — the README used to
  document four of the eight checks CI actually ran. Its wheel step builds into a
  temporary directory instead of globbing a persistent `dist/`, which could not be
  reproduced locally once `dist/` held more than one wheel.
- `.github/workflows/ci.yml` gains a `gate` job: one stable required-check context
  that aggregates the test matrix, so adding a Python version cannot silently narrow
  branch protection.
- The commit-message checker is wired up (`.pre-commit-config.yaml`, installed with
  `prek install --hook-type commit-msg`). Its docstring pointed at a `prek.toml` and a
  `CONTRIBUTING.md` that did not exist, and its allowed scopes were transplanted from
  another repository; both now match this one.
- Two comments that stated the opposite of current policy are corrected: the
  `pyproject.toml` note promising a pydantic dependency that was deliberately never
  added, and the `tests/test_conformance_fakes.py` docstring calling the backend
  protocol PROVISIONAL with a freeze gate still ahead of it.
- Read-only CI jobs no longer keep the checkout token while running repository code
  (`persist-credentials: false`); only the tag-pushing job keeps it.
- Added `CODEOWNERS`, issue and PR templates, `SECURITY.md`, and Dependabot for
  Actions and uv.
- `publish.yml` no longer triggers on a pushed `v*.*.*` tag; `workflow_dispatch` is
  the only entry point. The agent identity necessarily holds `contents: write` (it
  cannot push a branch otherwise), which makes creating a tag reachable by an agent,
  while dispatching needs `actions: write`, which it does not hold. Removing the
  trigger also removed the conditional job guards that existed solely to reconcile the
  two paths, so `create-tag` now always runs and the downstream jobs use plain
  `needs:` success semantics.

## [0.5.0] — 2026-08-16

### Release engineering

- The project is renamed **pontifex → pontonier**. The old name collided with
  the unrelated `pontifex-mcp` on PyPI, which is also MCP-adjacent. A pontonier
  is the engineer who builds pontoon bridges, which keeps the "not a bridge —
  what bridges are built from" framing. Nothing was ever published under the old
  name, so there is no compatibility shim and no deprecation period. Two
  runtime-visible strings moved with it: throwaway worktrees are now
  `pontonier-worktree-*`, and the default worktree git identity is
  `pontonier <pontonier@local>`. All three bridges override both, so neither
  string reaches a consumer.
- `pyproject.toml` is now the single source for the version. `__version__` reads
  the installed distribution metadata instead of repeating a literal, so the two
  can no longer disagree — the drift this replaces was real (`__version__` stuck
  at 0.3.0.dev0 across two bumps). `tests/test_version.py` now pins the
  installed metadata to the `pyproject.toml` declaration, which also catches an
  editable install left stale by a bump without a re-sync.
- Releases publish from CI. `.github/workflows/publish.yml` runs the full test
  gate, builds with `--no-sources`, creates the tag before publishing so a PyPI
  release can never exist without its git tag, uploads to PyPI through trusted
  publishing (OIDC, no long-lived token), and opens a GitHub Release with the
  changelog section as its notes. Adapted from the codex-in-claude workflow.

### Hardening

- `JobStore` now confines job ids to the shape it mints (`uuid4().hex`, 32
  lowercase hex). A job id is used verbatim as a path component under the
  workspace directory; previously a caller-supplied traversal-shaped id
  (`../…`) reached the filesystem join, and `status`/`discard`/`cancel` could
  read — or delete — a record-shaped directory outside the store root.
  Defense in depth: two of the three bridges pass `job_id: str` to the store
  unvalidated. Malformed ids now read as not-found in every public lookup
  (`status`, `result_payload`, `discard`, `cancel` — no wire-behavior change
  for consumers), and the `_job_dir` join itself raises as a backstop.
  Perturbation-verified: with the guards disabled, the new traversal test
  reaches a planted decoy record outside the store root.

### 0.5.0 (THE PROTOCOL FREEZE — `contract_api_version = 1`)

- `pontonier.backend` is FROZEN. The plan's freeze criterion — all three real
  adapters compile, type-check, and pass conformance and differential fixtures
  — was met and then exceeded: each bridge's production orchestration now
  stages every model-bearing run through its adapter's `prepare()`
  (codex-in-claude's `run_codex_exec`, moonbridge's `run_kimi_exec`, and
  claude-in-codex's sync tools + async job launch), so the adapters cannot
  drift from production behavior — they are production behavior.
- Freeze discipline, now binding: required Protocol members and required
  `BackendContract` fields are stable within a minor line; "additive" changes
  to a Protocol or frozen dataclass are breaking, so new behavior lands as
  defaulted fields or optional capability protocols (the pattern
  `effort_validation`, `dropped_flags`, and `artifact_paths` already
  followed).
- Deferred-findings ledger closed: the 0.3.0 note's schema-instruction seam
  resolved consumer-side (the Kimi re-plumb dissolved the duplication — one
  source, in the bridge that owns the strategy); classification's ambient
  extra-args context is recorded on the Codex adapter as acceptable while
  extra args are operator-owned process state.

### 0.4.0 (redaction strengthening — key-block handling flows into core)

- `PreparedRun.artifact_paths` (defaulted, non-breaking): NAMED staged paths,
  keyed like `RunOutcome.artifact_texts`. Freeze-window finding from the Kimi
  adapter: the flat `artifacts` tuple cannot tell the consumer which staged
  file is the answer channel, and it must be read back inside the `prepare()`
  context (staging is torn down on exit). `artifacts` stays as the
  cleanup/enumeration view; when both are set they must agree.
- `PreparedRun.dropped_flags` (defaulted, non-breaking): the channel for
  help-gated flags the preparation dropped because the installed CLI does not
  advertise them. Freeze-window finding from re-plumbing the Codex bridge's
  orchestration through its adapter: production surfaces dropped flags as
  compat warnings and reconciles reported model provenance from them, so a
  `prepare()` that discarded them could not carry the real hot path.

- `core.redaction` now redacts multi-line private-key blocks (PEM/PKCS8/OpenSSH/
  PGP) STATEFULLY — ported from the claude-in-codex bridge's local redactor,
  closing the pre-unification gap recorded under 0.3.0. The BEGIN/END markers
  stay visible so a reviewer sees what was dropped; every body line between them
  is replaced 1:1 with `[redacted: secret value]` (hunk line counts survive, so
  a redacted patch still applies); an UNTERMINATED block fails closed, redacted
  to end of input; a block never bleeds across `diff --git` headers or
  hunk/metadata boundaries; and the inline patterns scan the key pass's output,
  so a token sharing the END marker's physical line is still caught. Applies to
  `redact`/`DiffRedactor` (key masks flow through the same staged
  `masked_paths`/`inline_masks` accounting, including withhold dominance) and to
  `redact_text`/`redact_tree`/`exc_summary`.
- Five vendor patterns ported from the claude-in-codex bridge's local set:
  GitHub fine-grained PAT (`github_pat_`), GitLab PAT (`glpat-`), Anthropic
  key (`sk-ant-` — its hyphens put it out of the plain `sk-` run's reach, so
  it is not a redundant specialization), npm automation token (`npm_`), and
  PyPI upload token (`pypi-`). Unifying that bridge onto this engine without
  them would have weakened its coverage; codex-in-claude and moonbridge gain
  them outright.
- `StreamRedactor` — a stateful line-stream redactor for callers that sanitize
  output as it is produced (a worker scrubbing a child's stderr) and cannot
  buffer the full sensitive stream: key-block state spans calls, and the
  public writable `in_key_block` lets a caller that lost line fidelity
  (overlong-line truncation) fail closed until an END marker arrives.
- REMOVED the `-----BEGIN [A-Z ]*PRIVATE KEY-----` entry from
  `SECRET_VALUE_PATTERNS`. It masked the BEGIN marker itself while shipping the
  entire base64 body — a disclosure marker claiming coverage it did not have —
  and its missing trailing alternation never matched PGP's "PRIVATE KEY BLOCK"
  suffix at all. The stateful pass owns key material now; output for
  key-bearing input changes accordingly (markers visible, body dropped).

### 0.3.0 (protocol feedback from the three real adapters — still PROVISIONAL)

- `RunOutcome.events` is now an OPAQUE raw payload string instead of parsed
  event dicts. The Codex adapter showed that typed dicts forced eager parsing
  upstream of the tolerance boundary — real normalize layers must parse
  tolerantly so a malformed line degrades instead of raising. Its docs also now
  state that a backend may use neither the events nor the artifacts channel
  (the Claude adapter reads everything from the stdout envelope).
- `BackendContract.effort_validation` (defaulted, non-breaking) declares how
  pre-spend effort validation works: `enumerated` (Claude),
  `token_floor_plus_catalog` (Kimi — universal token floor, catalog-relative
  refinement, failing OPEN when the catalog cannot answer), or `shape_only`
  (Codex — upstream rejects bad values loudly; only argv-hostile shapes are
  refused locally).
- Deferred to the freeze window, recorded from adapter findings: a shared seam
  for the prompt-append schema-instruction text (currently duplicated in the
  Kimi bridge under a byte-parity test), and classification's ambient
  extra-args context.
- `JobStore.start` (and `start_idempotent` via passthrough) accepts
  `stdin_text`: streamed to the worker over a pipe by a daemon thread, never
  persisted — the transport for bridges whose prompts must stay off disk and
  off argv (the claude bridge's design). Default `None` keeps the prior
  DEVNULL behavior byte-identical.
- Known gap, discovered during the claude-in-codex context comparison:
  `core.redaction` has NO multi-line PEM/OpenSSH/PGP key-block handling — a
  private key pasted into a tracked file's diff (or returned in prose) is
  scrubbed only if the inline value patterns happen to match. claude-in-codex's
  local redactor handles these blocks statefully (failing closed on an
  unterminated block); that handling must flow into `core.redaction` BEFORE any
  bridge unifies onto the shared engine, or unification would weaken redaction.

### 0.2.0 (milestone M1 — conventions + provisional protocol)

- `pontonier.conventions.envelope`: shared error taxonomy — universal codes
  (the verified intersection across the three bridges), backend-prefixed code
  minting, feature-gated codes (`transfer`, `model_validation`,
  `empty_response_detection`), and per-code `RepairRule` tables parameterized
  by a `BackendErrorVocabulary`. Wire serialization deliberately stays
  consumer-side.
- `pontonier.conventions.prompts`: the shared framing/builders, with the host
  harness name as a parameter; `framings("Claude Code")` reproduces the
  source bridges' prose byte-for-byte (pinned by tests).
- `pontonier.conventions.annotations`: tool-annotation builders parameterized
  by declared effects (`AnnotationEffects`) instead of universal constants —
  the bridges' differing values are deliberate positions, now explicit.
- `pontonier.conventions.preflight`: `HelpProbe` (instance-cached `--help`
  feature detection, fail-open) generalizing the per-repo module.
- `pontonier.conventions.fingerprint`: the surface-digest / fingerprint-bump
  invariant as reusable, framework-agnostic mechanics.
- `pontonier.backend` (**PROVISIONAL**, `CONTRACT_API_VERSION = 0`):
  `BackendContract` (static facts: flag classes, failure-signature tables,
  field-scoped model-catalog authority, typed extra-args policy, isolation
  policy, limits), the `AgentBackend` protocol as a staged lifecycle
  (`validate_request` → `prepare` → `finalize`/`classify_failure`), shared
  `RunRequest`/`PreparedRun`/`RunOutcome`/`ExecResult` types, and a shared
  failure classifier with fixed precedence and a backend hook.
- `pontonier.testing`: importable, framework-agnostic test kit —
  surface-honesty phrase scanning, adapter/contract conformance checks
  (including the mandatory pre-spend effort-validation invariant), and
  sync/async pair parity. No pytest dependency.
- Three fake adapters (Codex-like, Kimi-like, Claude-like) validate that the
  provisional protocol expresses all three real invocation shapes.
- Deviation from plan, documented: no `pydantic` dependency was added — the
  backend/conventions layers are plain dataclasses, so the wheel still
  depends only on `anyio`. The planned `testing` extra is unnecessary for the
  same reason (the kit imports no test framework).

### 0.1.0 (milestone M0 — core extraction)

- `pontonier.core`: the CLI-agnostic machinery extracted from moonbridge's
  `_core` (jobs, worktree, gitdiff, redaction, runtime, gitproc, streamcap,
  idempotency, workspace, jsoncache), carrying the redaction
  trailing-newline fix and the orphan-process sweep.
- `WorktreeConfig`: worktree prefix, baseline-commit identity, and extra
  exclude pathspecs are per-consumer fields with behavioral tests.
- One-way dependency rule (`core` imports nothing from the rest) enforced by
  import-linter in CI.
