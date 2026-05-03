"""Configuration for CellWiki - paths, API keys, and settings."""

import logging
from pathlib import Path

from pydantic_settings import BaseSettings


def setup_logging(level: str = "INFO"):
    """Configure logging for CellWiki."""
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


class Settings(BaseSettings):
    """CellWiki configuration loaded from environment / .env file."""

    # OpenAI API settings
    openai_api_key: str = ""
    openai_base_url: str = ""
    openai_model: str = "qwen3.6-plus"

    # Logging
    log_level: str = "INFO"

    # Project paths (relative to project root)
    project_root: Path = Path(__file__).parent.parent
    data_dir: Path = project_root / "data"
    references_dir: Path = data_dir / "references"
    extraction_dir: Path = data_dir / "extraction"
    cell_ontology_dir: Path = data_dir / "cell_ontology"

    wiki_dir: Path = project_root / "wiki"
    wiki_cell_types_dir: Path = wiki_dir / "cell_types"

    # Cell Ontology
    cell_ontology_url: str = "https://purl.obolibrary.org/obo/cl.obo"
    cell_ontology_file: Path = cell_ontology_dir / "cl.obo"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
setup_logging(settings.log_level)


def ensure_dirs():
    """Create all required directories if they don't exist."""
    for d in [
        settings.data_dir,
        settings.references_dir,
        settings.extraction_dir,
        settings.cell_ontology_dir,
        settings.wiki_dir,
        settings.wiki_cell_types_dir,
    ]:
        d.mkdir(parents=True, exist_ok=True)
