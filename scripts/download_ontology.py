"""Download Cell Ontology OBO file."""

import requests
from cellwiki.config import settings


def download_ontology():
    """Download the Cell Ontology OBO file if it doesn't already exist."""
    settings.cell_ontology_dir.mkdir(parents=True, exist_ok=True)
    dest = settings.cell_ontology_file

    if dest.exists() and dest.stat().st_size > 0:
        print(f"Cell Ontology already exists: {dest} ({dest.stat().st_size / 1e6:.1f} MB)")
        return

    print(f"Downloading Cell Ontology from {settings.cell_ontology_url}...")
    resp = requests.get(settings.cell_ontology_url, stream=True)
    resp.raise_for_status()

    with open(dest, "wb") as f:
        for chunk in resp.iter_content(chunk_size=8192):
            f.write(chunk)

    size = dest.stat().st_size / 1e6
    print(f"Downloaded Cell Ontology: {dest} ({size:.1f} MB)")


if __name__ == "__main__":
    download_ontology()
