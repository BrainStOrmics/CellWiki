"""Cell Ontology loading, parsing, and cell type name resolution."""

import json
import re
from pathlib import Path
from cellwiki.config import settings


def load_cell_ontology(obo_path: str | Path | None = None) -> dict:
    """Parse an OBO file into structured data.

    Returns:
    {
        "terms": {
            "CL:0000003": {
                "name": "native cell",
                "is_a": ["CL:0000000"],
                "synonyms": ["native cell"],
                "definition": "...",
            },
            ...
        },
        "synonym_map": {
            "native cell": "CL:0000003",
            ...
        },
    }
    """
    if obo_path is None:
        obo_path = settings.cell_ontology_file

    obo_path = Path(obo_path)
    if not obo_path.exists():
        print(f"Warning: Cell Ontology file not found at {obo_path}")
        print("Run 'cellwiki init' or 'python scripts/download_ontology.py' first.")
        return {"terms": {}, "synonym_map": {}}

    terms = {}
    synonym_map = {}

    with open(obo_path, encoding="utf-8") as f:
        content = f.read()

    # Split into stanzas (Term blocks)
    stanzas = re.split(r"\n\[Term\]\n", content)

    for stanza in stanzas:
        lines = stanza.strip().split("\n")
        term_id = None
        name = None
        is_a = []
        synonyms = []
        definition = ""

        for line in lines:
            if line.startswith("id: "):
                term_id = line[4:].strip()
            elif line.startswith("name: "):
                name = line[6:].strip()
            elif line.startswith("is_a: "):
                parent_id = line[6:].strip().split("!")[0].strip()
                is_a.append(parent_id)
            elif line.startswith("synonym: "):
                # Extract quoted synonym
                match = re.search(r'"([^"]*)"', line)
                if match:
                    syn = match.group(1)
                    synonyms.append(syn)
            elif line.startswith("def: "):
                match = re.search(r'"([^"]*)"', line)
                if match:
                    definition = match.group(1)

        if term_id and name and term_id.startswith("CL:"):
            terms[term_id] = {
                "name": name,
                "is_a": is_a,
                "synonyms": synonyms,
                "definition": definition,
            }
            # Build synonym map (lowercase)
            # Prefer more specific terms: only overwrite if the new term has a shorter name
            # (shorter = more general, and we want general terms to map to the general CL ID)
            name_lower = name.lower()
            if name_lower not in synonym_map or len(name) < len(
                terms.get(synonym_map[name_lower], {}).get("name", "")
            ):
                synonym_map[name_lower] = term_id
            for syn in synonyms:
                syn_lower = syn.lower()
                if syn_lower not in synonym_map or len(syn) < len(
                    terms.get(synonym_map[syn_lower], {}).get("name", "")
                ):
                    synonym_map[syn_lower] = term_id

    return {"terms": terms, "synonym_map": synonym_map}


def load_cl_id_registry(registry_path: str | Path | None = None) -> dict:
    """Load manual CL ID mappings from cl_id_registry.json.

    Returns: {lowercase_cell_type_name: "CL:xxxxxxx", ...}
    """
    if registry_path is None:
        registry_path = settings.cell_ontology_dir / "cl_id_registry.json"
    registry_path = Path(registry_path)
    if not registry_path.exists():
        return {}
    with open(registry_path) as f:
        data = json.load(f)
    return {k.lower(): v for k, v in data.get("entries", {}).items()}


def load_manual_corrections(corrections_path: str | Path | None = None) -> dict:
    """Load manual corrections from manual_corrections.json.

    Returns: {lowercase_cell_type_name: {"cl_id_override": "CL:...", "marker_overrides": {...}}, ...}
    """
    if corrections_path is None:
        corrections_path = settings.cell_ontology_dir / "manual_corrections.json"
    corrections_path = Path(corrections_path)
    if not corrections_path.exists():
        return {}
    with open(corrections_path) as f:
        data = json.load(f)
    return {k.lower(): v for k, v in data.get("entries", {}).items()}


def _normalize_for_matching(s: str) -> str:
    """Strip special characters and normalize for comparison."""
    s = s.lower().strip()
    # Remove common prefixes/suffixes
    for suffix in [" cell", " cells", "-like", "+"]:
        s = s.removesuffix(suffix)
    for prefix in ["cd4 ", "cd8 "]:
        if s.startswith(prefix):
            s = s.removeprefix(prefix)
    # Normalize separators
    s = re.sub(r"[\s_\-]+", "", s)
    return s


def resolve_cell_type_to_cl(name: str, ontology: dict, registry: dict | None = None,
                            corrections: dict | None = None) -> str | None:
    """Try to match a cell type name to a Cell Ontology ID.

    Priority: manual corrections -> manual registry -> exact match -> normalized match.
    Fuzzy matching is deliberately avoided — it produces too many false positives.
    """
    if not name:
        return None

    lookup = name.lower().strip()

    # 1. Manual corrections (highest priority)
    if corrections and lookup in corrections:
        override = corrections[lookup].get("cl_id_override")
        if override:
            return override

    # 2. Manual registry
    if registry and lookup in registry:
        return registry[lookup]

    # 3. Exact match on name or synonym
    if ontology.get("synonym_map") and lookup in ontology["synonym_map"]:
        return ontology["synonym_map"][lookup]

    # 4. Normalized match (strip special chars, unify separators)
    lookup_norm = _normalize_for_matching(lookup)
    for term_name, cl_id in ontology.get("synonym_map", {}).items():
        if _normalize_for_matching(term_name) == lookup_norm:
            return cl_id

    return None


def get_parent_chain(cl_id: str, ontology: dict, max_depth: int = 5) -> list[str]:
    """Return the is_a chain from cl_id up to root."""
    chain = []
    current = cl_id
    for _ in range(max_depth):
        if current not in ontology.get("terms", {}):
            break
        chain.append(current)
        parents = ontology["terms"][current].get("is_a", [])
        if not parents:
            break
        current = parents[0]  # follow first parent
    return chain
