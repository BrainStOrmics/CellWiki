"""Knowledge base construction: merge extractions and build wiki pages."""

import json
import logging
from pathlib import Path
from cellwiki.config import settings
from cellwiki.models import ExtractionResult, WikiCellType

logger = logging.getLogger(__name__)


def save_extraction(result: ExtractionResult) -> str:
    """Save an ExtractionResult as JSON to the extraction directory.

    Returns the paper_id used for the saved file.
    """
    settings.extraction_dir.mkdir(parents=True, exist_ok=True)
    paper_id = result.paper.paper_id
    dest = settings.extraction_dir / f"{paper_id}.json"

    with open(dest, "w", encoding="utf-8") as f:
        # Convert to serializable dict
        data = result.model_dump(mode="json")
        json.dump(data, f, indent=2, ensure_ascii=False)

    return paper_id


def load_all_extractions() -> list[ExtractionResult]:
    """Load all saved extraction files from the extraction directory."""
    results = []
    for f in sorted(settings.extraction_dir.glob("*.json")):
        with open(f) as fh:
            data = json.load(fh)
        results.append(ExtractionResult(**data))
    return results


def merge_to_wiki(extractions: list[ExtractionResult]) -> dict[str, WikiCellType]:
    """Merge all extraction results into a dictionary of WikiCellType.

    Strategy: union (never delete). Multiple papers contribute markers,
    functions, and references to the same cell type.
    """
    wiki: dict[str, WikiCellType] = {}

    for extraction in extractions:
        for ct in extraction.cell_types:
            if not ct.standard_name:
                continue

            key = ct.standard_name
            if key not in wiki:
                # Create new wiki entry
                from cellwiki.wiki import _proper_title_case
                display = _proper_title_case(key)
                wiki[key] = WikiCellType(
                    standard_name=key,
                    display_name=display,
                    cl_id=ct.cl_id,
                    description=ct.description,
                    parent_type=ct.parent_type,
                )

            wiki_type = wiki[key]

            # Merge aliases
            wiki_type.aliases.add(ct.name)
            wiki_type.aliases.update(ct.synonyms)

            # Update CL ID if we have one
            if ct.cl_id and not wiki_type.cl_id:
                wiki_type.cl_id = ct.cl_id

            # Update parent type if missing
            if ct.parent_type and not wiki_type.parent_type:
                wiki_type.parent_type = ct.parent_type

            # Merge description (keep longer one)
            if len(ct.description) > len(wiki_type.description):
                wiki_type.description = ct.description

            # Merge markers (keyed by gene_symbol)
            for marker in ct.markers:
                entry = {
                    "marker_type": marker.marker_type.value,
                    "evidence": marker.evidence,
                    "strength": marker.strength,
                    "paper_id": ct.paper_ref.paper_id,
                }
                if marker.gene_symbol not in wiki_type.markers:
                    wiki_type.markers[marker.gene_symbol] = []
                # Avoid duplicate evidence
                if not any(e["evidence"] == marker.evidence for e in wiki_type.markers[marker.gene_symbol]):
                    # Detect conflicts: same gene, different marker_type from different papers
                    existing_types = {e["marker_type"] for e in wiki_type.markers[marker.gene_symbol]}
                    if existing_types and marker.marker_type.value not in existing_types:
                        entry["conflict"] = True
                        logger.info(f"Marker conflict for {marker.gene_symbol} in {key}: "
                                    f"{existing_types} vs {marker.marker_type.value}")
                    wiki_type.markers[marker.gene_symbol].append(entry)

            # Merge functions (keyed by description)
            for func in ct.functions:
                entry = {
                    "pathway": func.pathway,
                    "evidence": func.evidence,
                    "paper_id": ct.paper_ref.paper_id,
                }
                if func.description not in wiki_type.functions:
                    wiki_type.functions[func.description] = []
                if not any(e["evidence"] == func.evidence for e in wiki_type.functions[func.description]):
                    wiki_type.functions[func.description].append(entry)

            # Merge contexts
            for species in ct.species:
                if species not in wiki_type.contexts:
                    wiki_type.contexts[species] = {"tissues": [], "diseases": []}
                for t in ct.tissues:
                    if t not in wiki_type.contexts[species]["tissues"]:
                        wiki_type.contexts[species]["tissues"].append(t)
                for d in ct.diseases:
                    if d not in wiki_type.contexts[species]["diseases"]:
                        wiki_type.contexts[species]["diseases"].append(d)

            # Merge subpopulations
            wiki_type.subpopulations.update(ct.subpopulations)

            # Merge references
            ref_entry = {
                "paper_id": ct.paper_ref.paper_id,
                "title": ct.paper_ref.title,
                "doi": ct.paper_ref.doi,
                "year": ct.paper_ref.year,
            }
            if not any(r["paper_id"] == ref_entry["paper_id"] for r in wiki_type.references):
                wiki_type.references.append(ref_entry)

            # Track sources
            if ct.paper_ref.paper_id not in wiki_type.sources:
                wiki_type.sources.append(ct.paper_ref.paper_id)

    return wiki


def _merge_wiki_type(target: WikiCellType, source: WikiCellType):
    """Merge source into target (union strategy)."""
    target.aliases.update(source.aliases)
    if source.cl_id and not target.cl_id:
        target.cl_id = source.cl_id
    if source.parent_type and not target.parent_type:
        target.parent_type = source.parent_type
    if len(source.description) > len(target.description):
        target.description = source.description

    for gene, entries in source.markers.items():
        if gene not in target.markers:
            target.markers[gene] = []
        for entry in entries:
            if not any(e["paper_id"] == entry["paper_id"] and e["evidence"] == entry["evidence"]
                       for e in target.markers[gene]):
                target.markers[gene].append(entry)

    for desc, entries in source.functions.items():
        if desc not in target.functions:
            target.functions[desc] = []
        for entry in entries:
            if not any(e["paper_id"] == entry["paper_id"] and e["evidence"] == entry["evidence"]
                       for e in target.functions[desc]):
                target.functions[desc].append(entry)

    for species, info in source.contexts.items():
        if species not in target.contexts:
            target.contexts[species] = {"tissues": [], "diseases": []}
        for t in info["tissues"]:
            if t not in target.contexts[species]["tissues"]:
                target.contexts[species]["tissues"].append(t)
        for d in info["diseases"]:
            if d not in target.contexts[species]["diseases"]:
                target.contexts[species]["diseases"].append(d)

    target.subpopulations.update(source.subpopulations)
    for ref in source.references:
        if not any(r["paper_id"] == ref["paper_id"] for r in target.references):
            target.references.append(ref)
    for s in source.sources:
        if s not in target.sources:
            target.sources.append(s)


def deduplicate_by_cl_id(wiki: dict[str, WikiCellType]) -> dict[str, WikiCellType]:
    """Merge wiki entries that share the same valid CL ID.

    CL:0000000 is the root term and not useful for deduplication.
    Keeps the first entry as canonical, merges others into it.
    """
    cl_groups: dict[str, list[str]] = {}  # cl_id -> list of keys
    no_cl: list[str] = []

    for key, wt in wiki.items():
        if wt.cl_id and wt.cl_id != "CL:0000000":
            cl_groups.setdefault(wt.cl_id, []).append(key)
        else:
            no_cl.append(key)

    merged_keys = set()
    for cl_id, keys in cl_groups.items():
        if len(keys) < 2:
            merged_keys.update(keys)
            continue

        # Keep first as canonical, merge rest into it
        canonical = keys[0]
        merged_keys.add(canonical)
        for k in keys[1:]:
            _merge_wiki_type(wiki[canonical], wiki[k])
            wiki[canonical].aliases.add(wiki[k].display_name or k)
            wiki[canonical].aliases.add(k)

    # Rebuild wiki dict with only merged keys + no_cl entries
    result = {k: wiki[k] for k in merged_keys if k in wiki}
    result.update({k: wiki[k] for k in no_cl if k not in result})

    n_removed = len(wiki) - len(result)
    if n_removed > 0:
        print(f"  Deduplicated: {len(wiki)} -> {len(result)} pages (removed {n_removed} duplicates)")

    return result


def rebuild_wiki():
    """Full wiki rebuild: load all extractions, merge, deduplicate, regenerate pages."""
    extractions = load_all_extractions()
    if not extractions:
        print("No extractions found. Add papers first.")
        return

    wiki = merge_to_wiki(extractions)

    # Resolve CL IDs from ontology
    from cellwiki.ontology import load_cell_ontology, resolve_cell_type_to_cl, load_cl_id_registry, load_manual_corrections
    ontology = load_cell_ontology()
    registry = load_cl_id_registry()
    corrections = load_manual_corrections()

    for key, wt in wiki.items():
        if not wt.cl_id:
            wt.cl_id = resolve_cell_type_to_cl(wt.display_name or key, ontology, registry, corrections)
            if not wt.cl_id:
                wt.cl_id = resolve_cell_type_to_cl(key, ontology, registry, corrections)

    # Deduplicate by CL ID
    wiki = deduplicate_by_cl_id(wiki)

    # Generate wiki pages
    from cellwiki.wiki import generate_cell_type_page, generate_index_page

    settings.wiki_cell_types_dir.mkdir(parents=True, exist_ok=True)

    # Remove stale pages (keys no longer in wiki)
    valid_keys = set(wiki.keys())
    for existing in settings.wiki_cell_types_dir.glob("*.md"):
        if existing.stem not in valid_keys:
            existing.unlink()

    for key, wt in wiki.items():
        generate_cell_type_page(key, wt)

    generate_index_page(wiki)

    print(f"Generated {len(wiki)} cell type pages.")


# ============================================================
# CellWiki v2.0 — Multi-Omics Knowledge Merger
# ============================================================


class MultiOmicsMerger:
    """Merge multi-entity extractions into a unified WikiState."""

    def __init__(self):
        self.cell_types: dict = {}
        self.marker_genes: dict = {}
        self.tissues: dict = {}
        self.diseases: dict = {}
        self.methods: dict = {}
        self.trajectories: dict = {}

    def merge_cell_types(self, extractions: list) -> dict:
        """Merge cell type extractions (reuses existing merge_to_wiki logic)."""
        from cellwiki.knowledge import merge_to_wiki

        wiki = merge_to_wiki(extractions)
        self.cell_types = {
            key: {
                "standard_name": wt.standard_name,
                "display_name": wt.display_name,
                "cl_id": wt.cl_id,
                "parent_type": wt.parent_type,
                "description": wt.description,
                "markers": wt.markers,
                "functions": wt.functions,
                "subpopulations": list(wt.subpopulations),
                "references": wt.references,
                "sources": wt.sources,
                "identity": wt.identity,
                "state": wt.state,
                "context": wt.context,
            }
            for key, wt in wiki.items()
        }
        return self.cell_types

    def merge_marker_genes(self, extractions: list) -> dict:
        """Extract and merge marker gene information across papers."""
        from cellwiki.models import MarkerGene

        for extraction in extractions:
            for ct in extraction.cell_types:
                for marker in ct.markers:
                    gene = marker.gene_symbol
                    if gene not in self.marker_genes:
                        self.marker_genes[gene] = {
                            "gene_symbol": gene,
                            "cell_types_expressed": [],
                            "source_count": 0,
                            "sources": [],
                            "evidence_tier": 5,
                        }

                    mg = self.marker_genes[gene]
                    ct_name = ct.standard_name
                    if ct_name not in mg["cell_types_expressed"]:
                        mg["cell_types_expressed"].append(ct_name)

                    paper_id = extraction.paper.paper_id if extraction.paper else "unknown"
                    if paper_id not in mg["sources"]:
                        mg["sources"].append(paper_id)
                        mg["source_count"] += 1

        return self.marker_genes

    def merge_tissues(self, extractions: list) -> dict:
        """Extract and merge tissue information."""
        for extraction in extractions:
            for ct in extraction.cell_types:
                for tissue in ct.tissues:
                    tissue_key = tissue.lower().replace(" ", "_")
                    if tissue_key not in self.tissues:
                        self.tissues[tissue_key] = {
                            "name": tissue_key,
                            "display_name": tissue,
                            "cell_types_found": {},
                            "source_count": 0,
                            "sources": [],
                        }

                    t = self.tissues[tissue_key]
                    ct_name = ct.standard_name
                    if ct_name not in t["cell_types_found"]:
                        t["cell_types_found"][ct_name] = "present"

                    paper_id = extraction.paper.paper_id if extraction.paper else "unknown"
                    if paper_id not in t["sources"]:
                        t["sources"].append(paper_id)
                        t["source_count"] += 1

        return self.tissues

    def merge_diseases(self, extractions: list) -> dict:
        """Extract and merge disease associations."""
        for extraction in extractions:
            for ct in extraction.cell_types:
                for disease in ct.diseases:
                    disease_key = disease.lower().replace(" ", "_")
                    if disease_key not in self.diseases:
                        self.diseases[disease_key] = {
                            "name": disease_key,
                            "display_name": disease,
                            "associated_cell_types": {},
                            "source_count": 0,
                            "sources": [],
                        }

                    d = self.diseases[disease_key]
                    ct_name = ct.standard_name
                    if ct_name not in d["associated_cell_types"]:
                        d["associated_cell_types"][ct_name] = "associated"

                    paper_id = extraction.paper.paper_id if extraction.paper else "unknown"
                    if paper_id not in d["sources"]:
                        d["sources"].append(paper_id)
                        d["source_count"] += 1

        return self.diseases

    def detect_conflicts(self) -> list:
        """Detect conflicts across merged data."""
        conflicts = []

        # Marker conflicts: same gene, different types for same cell type
        for gene, mg in self.marker_genes.items():
            gene_markers = {}  # ct_name -> set of marker types
            for extraction in [None]:  # Placeholder - would need full extraction data
                pass

        return conflicts

    def assign_evidence_tiers(self):
        """Assign evidence tiers based on source counts."""
        for gene, mg in self.marker_genes.items():
            count = mg.get("source_count", 0)
            if count >= 3:
                mg["evidence_tier"] = 3
            elif count >= 1:
                mg["evidence_tier"] = 4
            else:
                mg["evidence_tier"] = 5

    def get_wiki_state(self) -> dict:
        """Return the complete WikiState."""
        return {
            "cell_types": self.cell_types,
            "marker_genes": self.marker_genes,
            "tissues": self.tissues,
            "diseases": self.diseases,
            "methods": self.methods,
            "trajectories": self.trajectories,
        }

