# Releasing

Publishing is irreversible: a version number on PyPI can be yanked but never reused.
Everything below is enforced by `.github/workflows/publish.yml`; this page exists so
the procedure does not have to be reverse-engineered from YAML.

## Who does what

| Step | Agent may do it | Human only |
| --- | --- | --- |
| Prepare the release commit (version + changelog) | yes, when asked | |
| Open the release PR | yes, when asked | |
| Merge the release PR | | yes |
| Dispatch the Publish workflow | | yes |
| Create or push a `v*` tag | | yes |
| Approve the `pypi` environment deployment | | yes |

The prohibition on the right-hand column is stated in
[AGENTS.md](../AGENTS.md#off-limits-without-explicit-human-instruction).

## 1. Prepare (agent-safe)

On a branch, in one commit:

1. Set the version in `pyproject.toml`. It is the single source — `pontonier.__version__`
   reads the installed distribution metadata, so there is no second literal to update.
2. Add a `## [X.Y.Z] — YYYY-MM-DD` section to `CHANGELOG.md`, replacing `## [Unreleased]`.
3. Run the reverse-dependency check: `scripts/check_consumers.sh`.
   It force-installs the built wheel into each consuming bridge and runs that bridge's
   suite, so a release candidate is proven against the real adapters, not only the fakes.
   With no arguments it expects the three bridges checked out beside this repository
   (`../codex-in-claude`, `../moonbridge`, `../claude-in-codex`); from any other layout,
   pass the checkouts explicitly: `scripts/check_consumers.sh /path/to/bridge ...`.
   Record the result in the release PR description.
4. Run the gate: `./scripts/check.sh`. `tests/test_version.py` pins the installed
   metadata to the `pyproject.toml` declaration, so a stale editable install fails here.
5. Commit as `chore(release): X.Y.Z` and open a PR.

Both files are checked again in CI before anything is published:

```sh
grep -Fq "version = \"X.Y.Z\"" pyproject.toml
grep -Fq "## [X.Y.Z]" CHANGELOG.md
```

A mismatch fails the `release-metadata` job before the build runs.

## 2. Publish (human only)

After the release PR is merged to `main`:

1. Actions → **Publish** → *Run workflow*, from `main`, entering the version.
   The workflow refuses to run a manual release from any other branch.
2. It validates the metadata, runs the full test gate, builds with `--no-sources`,
   then **creates and pushes the tag before publishing** — so a PyPI release can never
   exist without its git tag.
3. Approve the `pypi` environment when GitHub prompts. This is the last gate before
   an irreversible upload.
4. It publishes via PyPI trusted publishing (OIDC — no long-lived token exists) and
   opens a GitHub Release whose notes are the changelog section for that version.

Dispatch is the **only** trigger — pushing a `v*.*.*` tag does nothing. That is
deliberate: the agent identity can create tags (it holds `contents: write` so it can
push branches at all) but cannot dispatch a workflow, so this keeps the one entry
point in human hands. See [github-config.md](github-config.md#5-audit-the-agent-apps-permissions).

## If it goes wrong

- **Failed before `publish`** — fix and re-run. No artifact left the runner.
- **Failed during `publish`** — check PyPI before retrying. If the version uploaded,
  it is spent: yank it and release `X.Y.Z+1`.
- **Published but no GitHub Release** — re-run the workflow; `github-release` is
  idempotent and exits cleanly if the release already exists.
