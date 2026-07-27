"""Compatibility exports for the migrated structured extraction Adapter.

New product code imports from ``cellwiki.adapters``. This Module remains only
so the explicit legacy CLI can complete its deprecation window.
"""

from cellwiki.adapters.openai_structured_output import (  # noqa: F401
    ExtractionPolicy,
    StructuredExtractionError,
    extract_cell_types_from_chunk,
    extract_cell_types_from_paper,
)


__all__ = [
    "ExtractionPolicy",
    "StructuredExtractionError",
    "extract_cell_types_from_chunk",
    "extract_cell_types_from_paper",
]
