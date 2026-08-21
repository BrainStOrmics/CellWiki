"""Deterministic naming guards for cell-type extraction.

Naming discipline is enforced in code, not left to the extraction model:

- ``normalize_standard_name`` canonicalizes to lowercase snake_case so one
  entity cannot appear under differently-cased keys.  Windows filesystems are
  case-insensitive, so ``lrRC15_positive_fibroblast`` and
  ``lrrc15_positive_fibroblast`` must never become two wiki pages.
- ``is_cluster_identifier`` rejects paper-internal cluster labels (``c01``,
  ``SC-C4``, ``Ttr03``, ``t02``) as durable names.  Cluster labels may only
  survive as synonyms, never as standard_name or parent_type.
"""

from __future__ import annotations

import re

# Whole-token cluster labels: SC-C4, c01, c04-1, t02, Ttr03, CL1.
_CLUSTER_FULL = re.compile(
    r"^(?:"
    r"sc[-_]?c\d{1,2}"  # SC-C4 / sc_c4
    r"|c\d{2}(?:[-_]\d{1,2})?"  # c01 / c04-1
    r"|t\d{2}"  # t02
    r"|ttr\d{1,3}"  # Ttr03
    r"|[a-z]\d{2}"  # c01, m03, t02 (single letter followed by exactly two digits)
    r"|cl\d{1,4}"  # CL1 / Cl1234
    r")$"
)

# Cluster labels embedded in a snake_case compound name: cd4_c01_ccr7, ttr_like_cell.
_CLUSTER_SEGMENT = re.compile(
    r"(?:^|_)c\d{1,2}(?:_|$)"
    r"|(?:^|_)sc[-_]?c\d{1,2}(?:_|$)"
    r"|(?:^|_)ttr\d{1,3}(?:_|$)"
    r"|(?:^|_)[a-z]\d{2}(?:_|$)"
)


def normalize_standard_name(name: str) -> str:
    """Return a canonical lowercase snake_case standard_name key."""
    if not name:
        return ""
    cleaned = re.sub(r"[^A-Za-z0-9]+", "_", name.strip().casefold())
    return re.sub(r"_+", "_", cleaned).strip("_")


def is_cluster_identifier(value: str) -> bool:
    """True when the value is or embeds a paper-internal cluster label."""
    token = value.strip().casefold()
    if not token or token in {"cl", "sc", "c", "t", "ttr"}:
        return False
    if _CLUSTER_FULL.fullmatch(token):
        return True
    return _CLUSTER_SEGMENT.search(token) is not None


def canonicalize_standard_name(raw: str) -> tuple[str | None, str | None]:
    """Return (canonical_key, issue).

    ``canonical_key`` is None when the raw name is empty or is a paper-internal
    cluster label; ``issue`` explains why the caller must not use it as a
    standard_name.  Cluster identifiers never become durable names.
    """
    canonical = normalize_standard_name(raw)
    if not canonical:
        return None, "empty_standard_name"
    if is_cluster_identifier(canonical):
        return None, "cluster_id_standard_name"
    return canonical, None
