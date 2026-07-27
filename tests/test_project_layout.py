"""Tests for the maintained repository data-root layout."""

from pathlib import Path

from cellwiki.config import Settings


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_settings_do_not_expose_obsolete_project_roots() -> None:
    obsolete_fields = {
        "raw_dir",
        "raw_sources_dir",
        "raw_datasets_dir",
        "raw_ontologies_dir",
        "raw_notes_dir",
        "extractions_dir",
        "graphs_dir",
    }

    assert obsolete_fields.isdisjoint(Settings.model_fields)


def test_obsolete_project_roots_are_absent() -> None:
    obsolete_roots = ("raw", "extractions", "graphs", "local_tests")

    assert all(not (PROJECT_ROOT / root).exists() for root in obsolete_roots)
