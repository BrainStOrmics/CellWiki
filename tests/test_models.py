"""Tests for Pydantic data models."""

import json
import pytest
from cellwiki.models import (
    Marker, MarkerType, FunctionalCharacteristic, PaperReference,
    CellTypeExtract, ExtractionResult, WikiCellType,
)


class TestMarker:
    def test_create_positive_marker(self, sample_marker):
        assert sample_marker.gene_symbol == "CD3D"
        assert sample_marker.marker_type == MarkerType.POSITIVE
        assert sample_marker.evidence == "FACS gating"

    def test_marker_serialization(self, sample_marker):
        data = sample_marker.model_dump(mode="json")
        assert data["marker_type"] == "positive"
        roundtrip = Marker(**data)
        assert roundtrip.gene_symbol == "CD3D"


class TestPaperReference:
    def test_create_paper(self, sample_paper):
        assert sample_paper.paper_id == "test_paper_1"
        assert sample_paper.doi.startswith("10.1234")


class TestCellTypeExtract:
    def test_create_cell_type(self, sample_cell_type):
        assert sample_cell_type.standard_name == "cd8_t_cell"
        assert sample_cell_type.cl_id == "CL:0000625"
        assert len(sample_cell_type.markers) == 1
        assert len(sample_cell_type.species) == 1

    def test_cell_type_serialization(self, sample_cell_type):
        data = sample_cell_type.model_dump(mode="json")
        assert data["standard_name"] == "cd8_t_cell"
        roundtrip = CellTypeExtract(**data)
        assert roundtrip.standard_name == "cd8_t_cell"


class TestExtractionResult:
    def test_create_extraction(self, sample_extraction):
        assert len(sample_extraction.cell_types) == 1
        assert sample_extraction.paper.paper_id == "test_paper_1"

    def test_extraction_json_roundtrip(self, sample_extraction):
        data = sample_extraction.model_dump(mode="json")
        roundtrip = ExtractionResult(**data)
        assert len(roundtrip.cell_types) == 1
        assert roundtrip.cell_types[0].name == "CD8+ T cell"


class TestWikiCellType:
    def test_create_wiki_cell_type(self):
        wt = WikiCellType(
            standard_name="cd4_t_cell",
            display_name="CD4 T Cell",
            cl_id="CL:0000494",
        )
        assert wt.markers == {}
        assert wt.functions == {}
        assert wt.conflicts == []

    def test_merge_markers(self):
        wt = WikiCellType(
            standard_name="cd8_t_cell",
            display_name="CD8 T Cell",
        )
        wt.markers["CD8A"] = [
            {"marker_type": "positive", "evidence": "FACS", "paper_id": "paper1"}
        ]
        assert "CD8A" in wt.markers
        assert len(wt.markers["CD8A"]) == 1

    def test_conflict_tracking(self):
        wt = WikiCellType(
            standard_name="t_cell",
            display_name="T Cell",
            conflicts=["CD44: positive vs negative"],
        )
        assert len(wt.conflicts) == 1
