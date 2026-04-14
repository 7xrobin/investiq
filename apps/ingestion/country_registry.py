"""
Country registry loader.

Reads data/countries/config.yaml and provides typed access to the source
definitions used by the refresh_corpus_task.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml
from django.conf import settings

logger = logging.getLogger(__name__)

_REGISTRY_PATH = Path(settings.BASE_DIR) / "data" / "countries" / "config.yaml"

_registry_cache: dict | None = None


def _load_registry() -> dict[str, Any]:
    """Load and cache the YAML registry from disk."""
    global _registry_cache
    if _registry_cache is not None:
        return _registry_cache

    if not _REGISTRY_PATH.exists():
        raise FileNotFoundError(f"Country registry not found at {_REGISTRY_PATH}")

    with _REGISTRY_PATH.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    _registry_cache = data
    logger.info("Loaded country registry from %s", _REGISTRY_PATH)
    return data


def get_country_sources(jurisdiction: str) -> list[dict[str, Any]]:
    """
    Return all source definitions for a given jurisdiction code.

    Args:
        jurisdiction: e.g. 'DE', 'EU', 'UK', 'US'

    Returns:
        List of source dicts, each with keys: type, name, url, language,
        author, tags, and optionally year.
    """
    registry = _load_registry()
    countries = registry.get("countries", {})
    country_data = countries.get(jurisdiction, {})
    sources = country_data.get("sources", [])
    # Ensure jurisdiction is set on each source.
    for s in sources:
        s.setdefault("jurisdiction", jurisdiction)
        s.setdefault("language", "en")
    return sources


def get_all_jurisdictions() -> list[str]:
    """Return all jurisdiction codes defined in the registry."""
    registry = _load_registry()
    return list(registry.get("countries", {}).keys())


def get_academic_sources() -> list[dict[str, Any]]:
    """Return academic sources that apply globally."""
    registry = _load_registry()
    sources = registry.get("academic_sources", [])
    for s in sources:
        s.setdefault("jurisdiction", "GLOBAL")
        s.setdefault("source_type", "academic")
    return sources


def get_all_sources() -> list[dict[str, Any]]:
    """
    Return all sources across all jurisdictions plus academic sources.

    Useful for bulk ingestion.
    """
    all_sources: list[dict] = []
    for jurisdiction in get_all_jurisdictions():
        all_sources.extend(get_country_sources(jurisdiction))
    all_sources.extend(get_academic_sources())
    return all_sources
