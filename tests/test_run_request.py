"""``RunRequest.instructions_append`` (#12): the defaulted field a bridge uses to hand
caller-supplied instruction text to its adapter, which composes it BEHIND the bridge's
own framing. The library carries the text verbatim — normalization, caps, and framing
are bridge policy — so these tests pin the field's contract over its whole input
domain: absent, empty, blank, multi-line, non-ASCII, and the frozen-dataclass rules."""

from __future__ import annotations

import dataclasses
import re
from pathlib import Path

import pytest
from tests.test_conformance_fakes import ClaudeLikeBackend, CodexLikeBackend, KimiLikeBackend

from pontonier.backend import CONTRACT_API_VERSION
from pontonier.backend.protocol import RunRequest


def _request(**overrides: object) -> RunRequest:
    base: dict[str, object] = {"kind": "consult", "prompt": "q", "cwd": ".", "timeout_seconds": 1}
    return RunRequest(**{**base, **overrides})  # type: ignore[arg-type]


def test_defaults_to_none_and_keeps_the_freeze():
    # Defaulted, so every existing constructor call and every adapter built against v1
    # is untouched: the freeze permits a defaulted field, and the version does not move.
    assert _request().instructions_append is None
    assert CONTRACT_API_VERSION == 1


@pytest.mark.parametrize(
    "text",
    [
        "",  # empty: carried as-is, NOT coalesced to None — the bridge decides what blank means
        "   \n\t ",  # whitespace-only, same reason
        "Focus on concurrency.",
        "line one\n\nline three with trailing space \n",  # multi-line, verbatim
        "quotes \"double\" 'single' back\\slash",
        "non-ASCII: café — 日本語 — 😀",
    ],
)
def test_text_is_carried_verbatim(text: str):
    # No stripping, no encoding, no length policy here: the bytes a bridge validated and
    # fingerprinted are the bytes its adapter receives.
    assert _request(instructions_append=text).instructions_append == text


def test_field_is_frozen_like_the_rest_of_the_request():
    request = _request(instructions_append="x")
    with pytest.raises(dataclasses.FrozenInstanceError):
        request.instructions_append = "y"  # type: ignore[misc]


def test_field_is_last_and_keyword_reachable():
    # Appended after the existing fields so positional construction (which the bridges
    # do not use, but a defaulted-field addition must not reorder) is unchanged.
    names = [f.name for f in dataclasses.fields(RunRequest)]
    assert names[-1] == "instructions_append"
    assert names[:-1] == [
        "kind",
        "prompt",
        "cwd",
        "timeout_seconds",
        "schema",
        "model",
        "reasoning_effort",
        "budget_usd",
        "config_mode",
        "access",
        "isolation",
        "extra_args",
        "sanitize_aliases",
    ]


def test_field_is_separate_from_the_operator_channel():
    # The whole point of the field: caller text does not ride ``extra_args``, which the
    # protocol reserves for operator descriptors vetted by ExtraArgsPolicy.
    request = _request(instructions_append="persona")
    assert request.extra_args == ()


@pytest.mark.parametrize("backend_cls", [CodexLikeBackend, KimiLikeBackend, ClaudeLikeBackend])
async def test_adapters_without_the_concept_ignore_it(backend_cls: type):
    # The documented convention for optional request fields (config_mode/access): a
    # backend that lacks the concept ignores the field. The reference fakes predate it,
    # so a set value must leave their staged argv and stdin exactly as when it is unset.
    backend = backend_cls()
    sentinel = "CALLER-TEXT-SENTINEL-7f3a"
    plain = _request()
    with_text = _request(instructions_append=sentinel)
    async with backend.prepare(plain) as a, backend.prepare(with_text) as b:
        # Per-run temp paths (last-message, schema, handshake files) differ by design;
        # mask every absolute path so the staged runs compare structurally.
        def mask(value: object) -> object:
            if isinstance(value, str):
                return re.sub(r"/\S+", "<path>", value)
            if isinstance(value, tuple):
                return tuple(mask(v) for v in value)
            if isinstance(value, dict):
                return {k: mask(v) for k, v in value.items()}
            return value

        # Every PreparedRun channel, not just argv/stdin: env and staged artifacts are
        # the other places an adapter could start leaking the text.
        for name in ("argv", "env", "cwd", "stdin_text", "orphan_marker", "dropped_flags"):
            assert mask(getattr(a, name)) == mask(getattr(b, name)), name
        assert mask(a.artifact_paths) == mask(b.artifact_paths)
        assert len(a.artifacts) == len(b.artifacts)
        staged = "\n".join(Path(path).read_text() for path in b.artifacts if Path(path).is_file())
        assert sentinel not in " ".join(b.argv)
        assert sentinel not in " ".join(b.env.values())
        assert sentinel not in (b.stdin_text or "")
        assert sentinel not in staged
