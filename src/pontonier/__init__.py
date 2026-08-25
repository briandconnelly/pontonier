"""Pontonier: shared core library for cross-model agent-bridge MCP servers.

The supported public surface in this release is ``pontonier.core`` (see its
docstring for the module inventory) and ``pontonier.conventions`` /
``pontonier.testing``, and ``pontonier.backend`` (FROZEN at
``CONTRACT_API_VERSION = 1``: required members are stable within a minor line;
new behavior lands as defaulted fields or optional capability protocols).
Anything not documented as public is internal and may change without notice.
"""

from __future__ import annotations

from importlib.metadata import version as _version

# Single-sourced from the distribution metadata, which hatchling fills from the
# one declaration in pyproject.toml. Do not hardcode a literal here: the pair
# drifted once already (__version__ stuck at 0.3.0.dev0 across two bumps).
__version__ = _version("pontonier")

__all__ = ["__version__"]
