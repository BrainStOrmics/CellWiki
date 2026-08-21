"""Unit tests for the deterministic naming guards (services/naming.py)."""
import pytest

from cellwiki.services.naming import (
    canonicalize_standard_name,
    is_cluster_identifier,
    normalize_standard_name,
)


def test_normalize_lowercases_and_snakecases():
    assert normalize_standard_name("CD8+ T cells") == "cd8_t_cells"
    assert normalize_standard_name("  LRRC15 positive fibroblast  ") == "lrrc15_positive_fibroblast"
    assert normalize_standard_name("regulatory T-Cell") == "regulatory_t_cell"
    assert normalize_standard_name("") == ""


def test_normalize_collapses_dashes_spaces_and_duplicates():
    assert normalize_standard_name("a--b__c") == "a_b_c"
    assert normalize_standard_name("LRRC15  positive  fibroblast") == "lrrc15_positive_fibroblast"


@pytest.mark.parametrize(
    "value",
    [
        "c01", "c04", "t02", "ttr03", "ttr2", "SC-C4", "sc_c4", "c04-1", "CL1", "cl123",
        "cd4_c01_ccr7", "c01_t_cell",
    ],
)
def test_cluster_identifiers_are_detected(value):
    assert is_cluster_identifier(value), value


@pytest.mark.parametrize(
    "value",
    [
        "cd8_t_cell", "regulatory_t_cell", "tumor_associated_macrophage", "spp1_positive_macrophage",
        "th17", "il10_positive", "cd4_naive_t_cell", "plasmacytoid_dendritic_cell", "t_cell", "ttr_like_cell",
        "b_cell", "nk_cell",
    ],
)
def test_biological_names_are_not_cluster_identifiers(value):
    assert not is_cluster_identifier(value), value


def test_canonicalize_rejects_cluster_labels():
    canonical, issue = canonicalize_standard_name("SC-C4")
    assert canonical is None
    assert issue == "cluster_id_standard_name"


def test_canonicalize_normalizes_biological_names():
    canonical, issue = canonicalize_standard_name("LRRC15 positive fibroblast")
    assert canonical == "lrrc15_positive_fibroblast"
    assert issue is None
