"""HelpProbe: parsing, fail-open behavior, caching, and the advisory diagnostic."""

from __future__ import annotations

from pontonier.conventions import preflight
from pontonier.core import runtime


def _probe(**kwargs) -> preflight.HelpProbe:
    defaults = {
        "help_argv": ("fakecli", "--help"),
        "always_send_flags": ("--prompt", "--output-format"),
    }
    defaults.update(kwargs)
    return preflight.HelpProbe(**defaults)


def _stub_run(monkeypatch, stdout="", stderr="", missing=False):
    calls = []

    def fake(cmd, timeout_seconds):
        calls.append(cmd)
        err = runtime.BINARY_NOT_FOUND if missing else stderr
        return runtime.CommandRun(stdout, err, 127 if missing else 0, 1, False)

    monkeypatch.setattr(runtime, "run_sync_capture", fake)
    return calls


HELP_TEXT = """
Usage: fakecli [options]
  --prompt <text>       the prompt
  --output-format <f>   stream-json
  --model <alias>       optional model
"""


def test_parse_supported_extracts_long_flags():
    flags = preflight.parse_supported(HELP_TEXT)
    assert {"--prompt", "--output-format", "--model"} <= flags


def test_flag_support_parses_help(monkeypatch):
    _stub_run(monkeypatch, stdout=HELP_TEXT)
    fs = _probe().flag_support()
    assert fs.help_parsed
    assert preflight.is_supported("--model", fs)
    assert not preflight.is_supported("--nonexistent", fs)


def test_probe_failure_fails_open(monkeypatch):
    _stub_run(monkeypatch, missing=True)
    fs = _probe().flag_support()
    assert not fs.help_parsed
    # Fail OPEN: every flag treated as supported when the probe could not run.
    assert preflight.is_supported("--anything-at-all", fs)


def test_stderr_help_is_also_parsed(monkeypatch):
    # Some CLIs print help to stderr.
    _stub_run(monkeypatch, stdout="", stderr=HELP_TEXT)
    fs = _probe().flag_support()
    assert fs.help_parsed
    assert preflight.is_supported("--prompt", fs)


def test_cache_hit_avoids_reprobe(monkeypatch):
    calls = _stub_run(monkeypatch, stdout=HELP_TEXT)
    p = _probe()
    p.flag_support()
    p.flag_support()
    assert len(calls) == 1


def test_force_bypasses_cache(monkeypatch):
    calls = _stub_run(monkeypatch, stdout=HELP_TEXT)
    p = _probe()
    p.flag_support()
    p.flag_support(force=True)
    assert len(calls) == 2


def test_ttl_expiry_reprobes(monkeypatch):
    calls = _stub_run(monkeypatch, stdout=HELP_TEXT)
    p = _probe(cache_ttl_seconds=0.0)
    p.flag_support()
    p.flag_support()
    assert len(calls) == 2


def test_reset_cache(monkeypatch):
    calls = _stub_run(monkeypatch, stdout=HELP_TEXT)
    p = _probe()
    p.flag_support()
    p.reset_cache()
    p.flag_support()
    assert len(calls) == 2


def test_two_probes_do_not_share_cache(monkeypatch):
    calls = _stub_run(monkeypatch, stdout=HELP_TEXT)
    _probe().flag_support()
    _probe(help_argv=("othercli", "--help")).flag_support()
    assert len(calls) == 2


def test_missing_expected_flags_diagnostic(monkeypatch):
    _stub_run(monkeypatch, stdout="Usage: fakecli\n  --prompt <text>\n")
    p = _probe()
    fs = p.flag_support()
    assert p.missing_expected_flags(fs) == ["--output-format"]


def test_missing_expected_flags_empty_when_probe_failed(monkeypatch):
    _stub_run(monkeypatch, missing=True)
    p = _probe()
    assert p.missing_expected_flags(p.flag_support()) == []


def test_flag_support_fails_open_when_the_cli_cannot_be_executed(tmp_path, monkeypatch):
    """The in-repo caller of the broken contract (#16).

    _probe_help promises '"" on any failure (callers fail open)'. A CLI on PATH that
    cannot be executed — here a directory with the binary's name — used to escape
    run_sync_capture as a raised PermissionError and take flag_support with it.
    """
    entry = tmp_path / "path"
    (entry / "fakecli").mkdir(parents=True)
    monkeypatch.setenv("PATH", str(entry))
    assert _probe().flag_support() == preflight.FlagSupport(
        supported=frozenset(), help_parsed=False
    )
