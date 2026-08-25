# pontonier

Pontonier is the shared core library for cross-model agent-bridge MCP servers. An
agent bridge lets one agent harness call an agent that runs on a
different model. Three bridges use this library:

- [codex-in-claude](https://github.com/briandconnelly/codex-in-claude) — Claude Code → Codex CLI
- [moonbridge](https://github.com/briandconnelly/moonbridge) — Claude Code or Codex → Kimi CLI
- [claude-in-codex](https://github.com/briandconnelly/claude-in-codex) — Codex → Claude Code CLI

A pontonier is the engineer who builds pontoon bridges: pontonier is
not itself a bridge — it is what the bridges are built from.

## What is in the box

`pontonier.core` — backend-agnostic machinery, extracted from the
bridges' `_core` packages:

| Module | Purpose |
| --- | --- |
| `jobs` | Disk-backed, daemonless async job store |
| `worktree` | Throwaway git worktrees for delegated work |
| `gitdiff` | Bounded, redacted git diff gathering |
| `redaction` | Best-effort secret redaction for diffs and prose |
| `runtime` | Subprocess execution with bounded streams and cleanup |
| `gitproc` | Hardened git subprocess helpers |
| `streamcap` | Bounded stream capture |
| `idempotency` | On-disk idempotency-key index |
| `workspace` | MCP-root workspace resolution |
| `jsoncache` | Small JSON file cache |

**Rule:** `pontonier.core` never imports from the rest of the package. The gate
enforces this with import-linter; `src/pontonier/core/__init__.py` says why.

`pontonier.conventions` — the shared vocabulary bridges are built from:
error taxonomy + repair rules (`envelope`), host-parameterized prompt
framing (`prompts`), effect-parameterized tool annotations
(`annotations`), CLI `--help` feature detection (`preflight`), and the
surface-fingerprint invariant (`fingerprint`). Wire serialization stays
in each bridge.

`pontonier.backend` — **FROZEN** (`CONTRACT_API_VERSION = 1`): the
`BackendContract` static-facts dataclass, the `AgentBackend` staged run
lifecycle (`validate_request` → `prepare` → `finalize`/`classify_failure`),
and a shared failure classifier with fixed precedence. What the freeze
permits is stated once, in `src/pontonier/backend/__init__.py` — read it
before changing anything in that package.

`pontonier.testing` — importable, framework-agnostic test kit: surface
honesty (forbidden-phrase scanning against the built wire), adapter and
contract conformance, and sync/async tool-pair parity. Checks return
violation lists; wire them into any harness.

## Development

This project uses [uv](https://docs.astral.sh/uv/). One command runs the whole
gate — the same one CI runs:

```sh
uv sync
./scripts/check.sh
```

Setup, the individual gate steps, and the commit format are in
[CONTRIBUTING.md](CONTRIBUTING.md). Norms and prohibitions for AI agents working in
this repository are in [AGENTS.md](AGENTS.md). Releases: [docs/releasing.md](docs/releasing.md).
