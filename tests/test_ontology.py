# =============================================================================
# 本体论测试 —— 验证细胞本体论解析和 CL ID 解析
# =============================================================================

"""Tests for Cell Ontology parsing and CL ID resolution."""


from cellwiki.ontology import (
    resolve_cell_type_to_cl, load_cl_id_registry,
)


class TestCLIDRegistry:
    def test_load_registry_default_path(self):
        registry = load_cl_id_registry()
        assert isinstance(registry, dict)
        # Keys should be lowercase
        for key in registry:
            assert key == key.lower()

    def test_resolve_from_registry(self):
        registry = {"cd8+ temra cell": "CL:0000625"}
        result = resolve_cell_type_to_cl("CD8+ TEMRA Cell", {}, registry)
        assert result == "CL:0000625"

    def test_resolve_case_insensitive(self):
        registry = {"regulatory t cell": "CL:0000494"}
        result = resolve_cell_type_to_cl("Regulatory T Cell", {}, registry)
        assert result == "CL:0000494"


class TestResolveCellType:
    def test_exact_match(self):
        # Build a minimal ontology with known entries
        ontology = {
            "terms": {
                "CL:0000625": {"name": "CD8-positive, alpha-beta T cell"},
                "CL:0000494": {"name": "CD4-positive, alpha-beta T cell"},
            },
            "synonym_map": {
                "cd8-positive, alpha-beta t cell": "CL:0000625",
                "cd8+ t cell": "CL:0000625",
                "cd8 t cell": "CL:0000625",
            },
        }
        result = resolve_cell_type_to_cl("cd8+ t cell", ontology)
        assert result == "CL:0000625"

    def test_no_match_returns_none(self):
        ontology = {"terms": {}, "synonym_map": {}}
        result = resolve_cell_type_to_cl("alien_cell_type", ontology)
        assert result is None

    def test_registry_takes_priority_over_ontology(self):
        registry = {"t cell": "CL:9999999"}
        ontology = {
            "terms": {"CL:0000001": {"name": "T cell"}},
            "synonym_map": {"t cell": "CL:0000001"},
        }
        result = resolve_cell_type_to_cl("T Cell", ontology, registry)
        assert result == "CL:9999999"
