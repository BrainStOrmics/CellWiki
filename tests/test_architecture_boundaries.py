"""Static and runtime checks for product Module dependency direction."""

from __future__ import annotations

import ast
import tomllib
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = PROJECT_ROOT / "src" / "cellwiki"


def _imports(path: Path) -> set[str]:
    """Return absolute import names without importing the inspected Module."""

    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
        elif isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
    return names


def test_ingest_module_depends_on_extraction_interface_not_legacy_implementation() -> None:
    imports = _imports(PACKAGE_ROOT / "services" / "ingest.py")

    assert "cellwiki.services.extraction" in imports
    assert "cellwiki.llm_extract" not in imports


def test_default_ingest_extractor_is_an_external_adapter(tmp_path: Path) -> None:
    from cellwiki.adapters.openai_extraction import OpenAIChunkExtractor
    from cellwiki.services.ingest import IngestService

    ingest = IngestService(tmp_path)

    assert isinstance(ingest.extractor, OpenAIChunkExtractor)


def test_projection_module_depends_on_renderer_interface_not_legacy_modules() -> None:
    imports = _imports(PACKAGE_ROOT / "services" / "projection.py")

    assert "cellwiki.services.rendering" in imports
    assert "cellwiki.knowledge" not in imports
    assert "cellwiki.wiki" not in imports


def test_default_projection_renderer_is_an_external_adapter(tmp_path: Path) -> None:
    from cellwiki.adapters.wiki_renderer import CellWikiMarkdownRenderer
    from cellwiki.services.projection import ProjectionService

    projection = ProjectionService(tmp_path)

    assert isinstance(projection.renderer, CellWikiMarkdownRenderer)


def test_product_modules_use_domain_extraction_contracts() -> None:
    product_modules = [
        PACKAGE_ROOT / "services" / "ingest.py",
        PACKAGE_ROOT / "services" / "extraction.py",
        PACKAGE_ROOT / "services" / "projection.py",
        PACKAGE_ROOT / "services" / "rendering.py",
        PACKAGE_ROOT / "services" / "quality.py",
        PACKAGE_ROOT / "services" / "central_writer.py",
        PACKAGE_ROOT / "adapters" / "openai_extraction.py",
        PACKAGE_ROOT / "adapters" / "wiki_renderer.py",
    ]

    offenders = [
        path.relative_to(PACKAGE_ROOT).as_posix()
        for path in product_modules
        if "cellwiki.models" in _imports(path)
    ]

    assert offenders == []


def test_legacy_extraction_model_exports_resolve_to_domain_contracts() -> None:
    from cellwiki.domain.extraction import ExtractionResult
    from cellwiki.models import ExtractionResult as LegacyExtractionResult

    assert LegacyExtractionResult is ExtractionResult


def test_openai_adapter_owns_structured_extraction_implementation() -> None:
    imports = _imports(PACKAGE_ROOT / "adapters" / "openai_extraction.py")

    assert "cellwiki.adapters.openai_structured_output" in imports
    assert "cellwiki.llm_extract" not in imports


def test_wiki_renderer_owns_merge_and_markdown_implementation() -> None:
    imports = _imports(PACKAGE_ROOT / "adapters" / "wiki_renderer.py")

    assert "cellwiki.adapters.wiki_knowledge" in imports
    assert "cellwiki.adapters.markdown_renderer" in imports
    assert "cellwiki.knowledge" not in imports
    assert "cellwiki.wiki" not in imports


def test_product_packages_do_not_import_legacy_graph_workflows() -> None:
    forbidden = {
        "cellwiki.ingest_graph",
        "cellwiki.lint_graph",
        "cellwiki.query_graph",
        "cellwiki.research_graph",
        "cellwiki.orchestrator",
        "graphs",
    }
    product_roots = ["api", "agent", "domain", "services", "adapters"]
    offenders: list[str] = []

    for product_root in product_roots:
        for path in (PACKAGE_ROOT / product_root).rglob("*.py"):
            if _imports(path) & forbidden:
                offenders.append(path.relative_to(PACKAGE_ROOT).as_posix())

    assert offenders == []


def test_legacy_implementations_live_under_legacy_package() -> None:
    legacy_modules = {
        "audit",
        "extract",
        "graph_analysis",
        "ingest_graph",
        "lint_graph",
        "ontology",
        "orchestrator",
        "query_graph",
        "research_graph",
        "visualization",
    }

    for module in legacy_modules:
        implementation = PACKAGE_ROOT / "legacy" / f"{module}.py"
        compatibility = PACKAGE_ROOT / f"{module}.py"
        assert implementation.is_file(), module
        assert f"cellwiki.legacy.{module}" in _imports(compatibility), module

    assert (PACKAGE_ROOT / "legacy" / "graphs").is_dir()
    assert not (PROJECT_ROOT / "src" / "graphs").exists()


def test_packaging_contains_only_the_cellwiki_package_tree() -> None:
    configuration = tomllib.loads(
        (PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    )

    assert configuration["tool"]["setuptools"]["packages"]["find"]["include"] == [
        "cellwiki*"
    ]
