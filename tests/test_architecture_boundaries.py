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


def test_product_modules_use_domain_extraction_contracts() -> None:
    product_modules = [
        PACKAGE_ROOT / "services" / "quality.py",
        PACKAGE_ROOT / "adapters" / "wiki_renderer.py",
        PACKAGE_ROOT / "services" / "naming.py",
    ]

    offenders = [
        path.relative_to(PACKAGE_ROOT).as_posix()
        for path in product_modules
        if "cellwiki.models" in _imports(path)
    ]

    assert offenders == []


def test_extraction_model_exports_resolve_to_domain_contracts() -> None:
    from cellwiki.domain.extraction import ExtractionResult
    from cellwiki.models import ExtractionResult as ModelExtractionResult

    assert ModelExtractionResult is ExtractionResult


def test_structured_extraction_adapter_uses_the_current_adapter_module() -> None:
    imports = _imports(PACKAGE_ROOT / "adapters" / "openai_structured_output.py")

    assert "cellwiki.llm_extract" not in imports


def test_wiki_renderer_owns_merge_and_markdown_implementation() -> None:
    imports = _imports(PACKAGE_ROOT / "adapters" / "wiki_renderer.py")

    assert "cellwiki.adapters.wiki_knowledge" in imports
    assert "cellwiki.adapters.markdown_renderer" in imports
    assert "cellwiki.knowledge" not in imports
    assert "cellwiki.wiki" not in imports


def test_product_packages_do_not_import_retired_legacy_workflows() -> None:
    forbidden = {
        "cellwiki.legacy",
        "cellwiki.ingest_graph",
        "cellwiki.lint_graph",
        "cellwiki.query_graph",
        "cellwiki.research_graph",
        "cellwiki.orchestrator",
        "cellwiki.knowledge",
        "cellwiki.llm_extract",
        "cellwiki.wiki",
        "graphs",
    }
    product_roots = ["api", "agent", "domain", "services", "adapters"]
    offenders: list[str] = []

    for product_root in product_roots:
        for path in (PACKAGE_ROOT / product_root).rglob("*.py"):
            if _imports(path) & forbidden:
                offenders.append(path.relative_to(PACKAGE_ROOT).as_posix())

    assert offenders == []


def test_retired_legacy_modules_are_absent() -> None:
    retired_modules = {
        "audit",
        "cli",
        "extract",
        "graph_analysis",
        "ingest_graph",
        "knowledge",
        "lint_graph",
        "llm_extract",
        "ontology",
        "orchestrator",
        "query_graph",
        "visualization",
        "wiki",
    }

    assert not (PACKAGE_ROOT / "legacy").exists()
    assert not (PACKAGE_ROOT / "research_graph.py").exists()
    for module in retired_modules:
        assert not (PACKAGE_ROOT / f"{module}.py").exists(), module


def test_packaging_contains_only_the_cellwiki_package_tree() -> None:
    configuration = tomllib.loads(
        (PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    )

    assert configuration["tool"]["setuptools"]["packages"]["find"]["include"] == [
        "cellwiki*"
    ]