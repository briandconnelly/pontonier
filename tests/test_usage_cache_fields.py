"""``Usage.cached_input_tokens`` / ``cache_creation_input_tokens``: defaulted fields so the
three adapters can carry the cache accounting their bridges already report (Codex and Kimi
``cached_input_tokens``; Claude ``cache_read_input_tokens`` / ``cache_creation_input_tokens``)
without a protocol break. Today every adapter's ``finalize`` drops these figures."""

from __future__ import annotations

import dataclasses

import pytest

from pontonier.backend import CONTRACT_API_VERSION
from pontonier.backend.protocol import Usage


def test_cache_fields_default_to_none_and_keep_the_freeze():
    usage = Usage()
    assert usage.cached_input_tokens is None
    assert usage.cache_creation_input_tokens is None
    assert CONTRACT_API_VERSION == 1


def test_positional_construction_is_unchanged():
    # Adapters build Usage(input, output, total, cost) positionally or by keyword; the
    # new fields are appended, so those calls keep their meaning.
    usage = Usage(1, 2, 3, 0.5)
    assert (usage.input_tokens, usage.output_tokens, usage.total_tokens, usage.cost_usd) == (
        1,
        2,
        3,
        0.5,
    )
    assert usage.cached_input_tokens is None
    assert usage.cache_creation_input_tokens is None


@pytest.mark.parametrize("value", [0, 1, 123_456])
def test_cache_fields_carry_integers_verbatim(value: int):
    usage = Usage(cached_input_tokens=value, cache_creation_input_tokens=value)
    assert usage.cached_input_tokens == value
    assert usage.cache_creation_input_tokens == value


def test_cache_fields_are_frozen_and_last():
    usage = Usage(cached_input_tokens=1)
    with pytest.raises(dataclasses.FrozenInstanceError):
        usage.cached_input_tokens = 2  # type: ignore[misc]
    names = [f.name for f in dataclasses.fields(Usage)]
    assert names[-2:] == ["cached_input_tokens", "cache_creation_input_tokens"]
