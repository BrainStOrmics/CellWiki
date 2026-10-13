"""Committed Wiki projection for read-only annotation evidence queries."""

import json
import re
import sqlite3
import subprocess
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator, Literal

import yaml

from cellwiki.domain.annotation import (
    AnnotationCandidate, AnnotationContext, AnnotationEvidence,
    AnnotationRequest, AnnotationResponse,
)


class AnnotationUnavailable(RuntimeError):
    def __init__(self, code: str = "KNOWLEDGE_UNAVAILABLE") -> None:
        self.code = code
        super().__init__(code)


def _key(value: str) -> str:
    return " ".join(value.replace("_", " ").split()).casefold()


@dataclass(frozen=True)
class MarkerEvidence:
    gene: str
    polarity: str
    tier: int
    paper_id: str
    line: int


@dataclass(frozen=True)
class CellPage:
    path: str
    metadata: dict
    markers: list[MarkerEvidence]
    contexts: list[tuple[str, list[str], list[str]]]
    references: dict[str, dict]


def _parse_page(path: str, text: str, source_ids: set[str]) -> CellPage:
    if not text.startswith("---\n"):
        raise AnnotationUnavailable()
    frontmatter, separator, body = text[4:].partition("\n---\n")
    metadata = yaml.safe_load(frontmatter)
    if not separator or not isinstance(metadata, dict):
        raise AnnotationUnavailable()
    for field in ("standard_name", "display_name"):
        if not isinstance(metadata.get(field), str) or not metadata[field].strip():
            raise AnnotationUnavailable()
    if not re.fullmatch(r"[a-z0-9_]+", metadata["standard_name"]):
        raise AnnotationUnavailable()
    for field in ("aliases", "positive_markers", "negative_markers", "species", "tissues", "conflicts"):
        if not isinstance(metadata.get(field), list):
            raise AnnotationUnavailable()
        if field != "conflicts" and any(not isinstance(value, str) for value in metadata[field]):
            raise AnnotationUnavailable()
    references = {}
    for reference in metadata.get("references", []):
        if not isinstance(reference, dict) or not isinstance(reference.get("paper_id"), str):
            raise AnnotationUnavailable()
        if reference["paper_id"] in references:
            raise AnnotationUnavailable()
        references[reference["paper_id"]] = reference
    markers = []
    contexts = []
    reference_lines: list[tuple[int, str]] = []
    section = ""
    species = ""
    tissues: list[str] = []
    diseases: list[str] = []
    for line_number, line in enumerate(text.splitlines(), 1):
        if line.startswith("## "):
            if species:
                contexts.append((species, tissues, diseases))
                species, tissues, diseases = "", [], []
            section = line[3:].strip()
        if section == "Contexts":
            if line.startswith("### "):
                if species:
                    contexts.append((species, tissues, diseases))
                species, tissues, diseases = line[4:].strip(), [], []
            if line.startswith("**Tissues:**"):
                tissues = re.findall(r"\[\[([^\]|]+)(?:\|[^\]]+)?\]\]", line)
            if line.startswith("**Diseases:**"):
                diseases = re.findall(r"\[\[([^\]|]+)(?:\|[^\]]+)?\]\]", line)
        if section == "Markers" and line.startswith("|"):
            columns = [value.strip() for value in line.strip("|").split("|")]
            if len(columns) != 4 or columns[1] not in {"positive", "negative"}:
                continue
            tier_match = re.fullmatch(r"(?:Evidence:\s*)?Tier ([1-5])", columns[2])
            source_match = re.fullmatch(r"\[([^\]]+)\]\(#references\)", columns[3])
            if tier_match is None or source_match is None:
                continue
            paper_id = source_match[1]
            if paper_id not in references or paper_id not in source_ids:
                continue
            gene = columns[0].removeprefix("[[").removesuffix("]]")
            markers.append(MarkerEvidence(gene, columns[1], int(tier_match[1]), paper_id, line_number))
        if section == "References":
            if line.startswith("- "):
                reference_lines.append((line_number, line[2:].strip()))
            explicit = re.match(r"^- \[([^\]]+)\]\([^)]*\)\s*(.*)$", line)
            if explicit and explicit[1] in references:
                reference = references[explicit[1]]
                doi = re.search(r"\[(10\.[^\]]+)\]\((https?://[^)]+)\)", explicit[2])
                if doi:
                    reference.setdefault("doi", doi[1])
                    reference.setdefault("url", doi[2])
                    reference.setdefault("title", explicit[2][:doi.start()].strip())
    if len(references) == 1 and len(reference_lines) == 1:
        reference = next(iter(references.values()))
        doi = re.search(r"\[(10\.[^\]]+)\]\((https?://[^)]+)\)", reference_lines[0][1])
        if doi:
            reference.setdefault("doi", doi[1])
            reference.setdefault("url", doi[2])
            reference.setdefault("title", reference_lines[0][1][:doi.start()].strip())
    if species:
        contexts.append((species, tissues, diseases))
    return CellPage(path, metadata, markers, contexts, references)


class AnnotationSupportService:
    def __init__(self, root: Path, maintenance_guard: Callable | None = None):
        self.root = Path(root).resolve()
        self.maintenance_guard = maintenance_guard

    def _git(self, *arguments: str, input_data: bytes | None = None) -> bytes:
        result = subprocess.run(
            ["git", "-C", str(self.root), *arguments], input=input_data,
            capture_output=True, timeout=20, check=False,
        )
        if result.returncode:
            raise AnnotationUnavailable()
        return result.stdout

    @contextmanager
    def _capture(self) -> Iterator[str]:
        database = self.root / "data/runtime/cellwiki.db"
        connection = None
        try:
            if database.exists():
                connection = sqlite3.connect(database.as_uri() + "?mode=rw", uri=True, timeout=0)
                connection.execute("BEGIN IMMEDIATE")
                active = connection.execute(
                    "SELECT 1 FROM agent_runs WHERE status NOT IN ('succeeded','rejected','failed','cancelled') LIMIT 1"
                ).fetchone()
                pending = connection.execute("SELECT 1 FROM pending_diffs WHERE status='pending' LIMIT 1").fetchone()
                if active or pending:
                    raise AnnotationUnavailable("KNOWLEDGE_BUSY")
                resolved = connection.execute("SELECT status, payload FROM pending_diffs").fetchall()
                if any(
                    status in {"accepted", "rejected"}
                    and json.loads(payload).get("data", {}).get("maintenance", {}).get("status") != "ok"
                    for status, payload in resolved
                ):
                    raise AnnotationUnavailable("KNOWLEDGE_BUSY")
                self._assert_no_unapproved_run_leftovers(connection)
            toplevel = self._git("rev-parse", "--show-toplevel").decode().strip()
            if Path(toplevel).resolve() != self.root:
                raise AnnotationUnavailable()
            sha = self._git("rev-parse", "--verify", "HEAD^{commit}").decode().strip()
            yield sha
        except sqlite3.OperationalError as error:
            if "locked" in str(error).lower():
                raise AnnotationUnavailable("KNOWLEDGE_BUSY") from None
            raise AnnotationUnavailable() from None
        finally:
            if connection is not None:
                connection.rollback()
                connection.close()

    def _assert_no_unapproved_run_leftovers(self, connection: sqlite3.Connection) -> None:
        """Block when a failed/cancelled run left committed knowledge unapproved.

        Each such run's approved tip is where its last resolved unit landed; its
        segment ends where the next run started, because runs are strictly
        serialized and a pending unit blocks the next run. Checking only the
        latest run would let a later succeeded run absorb and hide an older
        run's leftover commits: those commits sit before the next run's snapshot
        and therefore never enter any unit's patch.
        """
        runs = connection.execute(
            "SELECT run_id, payload FROM agent_runs ORDER BY rowid"
        ).fetchall()
        for index, (run_id, payload) in enumerate(runs):
            run = json.loads(payload)
            if run["status"] not in {"failed", "cancelled"}:
                continue
            baseline = run.get("snapshot_commit")
            last_unit = connection.execute(
                "SELECT status, payload FROM pending_diffs WHERE run_id=? "
                "ORDER BY created_at DESC, rowid DESC LIMIT 1",
                (run_id,),
            ).fetchone()
            if last_unit:
                unit = json.loads(last_unit[1])
                maintenance = unit.get("data", {}).get("maintenance", {})
                reverts = unit.get("data", {}).get("revert_commits", [])
                baseline = maintenance.get("commit") or (
                    unit.get("head_commit") if last_unit[0] == "accepted" else
                    reverts[-1] if reverts else unit.get("snapshot_commit")
                ) or baseline
            bound = "HEAD"
            if index + 1 < len(runs):
                bound = json.loads(runs[index + 1][1]).get("snapshot_commit") or "HEAD"
            if not baseline:
                raise AnnotationUnavailable("KNOWLEDGE_BUSY")
            if baseline != bound and self._git(
                "diff", "--name-only", baseline, bound, "--", "wiki", "raw", "schema.md"
            ):
                raise AnnotationUnavailable("KNOWLEDGE_BUSY")

    def _snapshot(self) -> tuple[str, dict[str, str], set[str]]:
        if self.maintenance_guard is not None:
            with self.maintenance_guard():
                with self._capture() as sha:
                    version = sha
        else:
            with self._capture() as sha:
                version = sha
        listing = self._git("ls-tree", "-rz", version, "--", "wiki", "raw", "schema.md")
        blobs = []
        sources = set()
        for entry in listing.split(b"\0"):
            if not entry:
                continue
            attributes, filename = entry.split(b"\t", 1)
            mode, kind, object_id = attributes.split()
            path = filename.decode("utf-8")
            if path.startswith("raw/") and len(path.split("/")) > 2:
                sources.add(path.split("/")[1])
            if path == "schema.md" or (path.startswith("wiki/") and path.endswith(".md")):
                if mode not in {b"100644", b"100755"} or kind != b"blob":
                    raise AnnotationUnavailable()
                blobs.append((path, object_id))
        data = self._git("cat-file", "--batch", input_data=b"\n".join(object_id for _, object_id in blobs) + b"\n")
        if len(data) > 32_000_000:
            raise AnnotationUnavailable()
        files = {}
        offset = 0
        for path, _ in blobs:
            end = data.index(b"\n", offset)
            size = int(data[offset:end].split()[-1])
            offset = end + 1
            files[path] = data[offset:offset + size].decode("utf-8").replace("\r\n", "\n")
            offset += size + 1
        return version, files, sources

    def query(self, request: AnnotationRequest) -> AnnotationResponse:
        try:
            return self._query(request)
        except AnnotationUnavailable:
            raise
        except (ValueError, KeyError, TypeError, OSError, yaml.YAMLError, subprocess.TimeoutExpired):
            raise AnnotationUnavailable() from None

    def _query(self, request: AnnotationRequest) -> AnnotationResponse:
        version, files, sources = self._snapshot()
        schema = files.get("schema.md", "")
        fence = chr(96) * 3
        block = re.search(fence + r"(?:yaml|yml) cellwiki-schema\s*\n(.*?)\n" + fence, schema, re.DOTALL)
        contract = yaml.safe_load(block[1]) if block else None
        if not isinstance(contract, dict) or contract.get("schema_version") != 2:
            raise AnnotationUnavailable()
        page_contract = contract.get("pages", {}).get("cell_type", {})
        if page_contract.get("path") != "wiki/cell_types/{id}.md" or page_contract.get("identity") != "standard_name":
            raise AnnotationUnavailable()
        pages = [_parse_page(path, text, sources) for path, text in sorted(files.items())
                 if path.startswith("wiki/cell_types/") and path.count("/") == 2]
        if not pages or len({page.metadata["standard_name"] for page in pages}) != len(pages):
            raise AnnotationUnavailable()
        aliases: dict[str, set[str]] = {}
        for path, text in files.items():
            if path.startswith(("wiki/tissues/", "wiki/diseases/")):
                metadata = yaml.safe_load(text[4:].partition("\n---\n")[0]) if text.startswith("---\n") else {}
                if isinstance(metadata, dict):
                    identity = Path(path).stem
                    for value in [identity, metadata.get("name"), metadata.get("display_name")]:
                        if isinstance(value, str):
                            aliases.setdefault(_key(value), set()).add(_key(identity))
        def context(value: str | None, values: list[str], species: bool = False) -> str:
            if not value or not values:
                return "unknown"
            names = {_key(item) for item in values}
            if _key(value) in names or len(aliases.get(_key(value), set()) & names) == 1:
                return "matched"
            return "mismatched" if species else "cross_context"

        ranked = []
        warnings = []
        positive_input = {value.casefold(): value for value in request.top_markers}
        absent_input = {value.casefold(): value for value in request.low_or_absent_markers}
        for page in pages:
            metadata = page.metadata
            positives = {value.casefold() for value in metadata["positive_markers"]}
            negatives = {value.casefold() for value in metadata["negative_markers"]}
            grounded_positive = {marker.gene.casefold() for marker in page.markers if marker.polarity == "positive" and marker.tier <= 4} & positives
            grounded_negative = {marker.gene.casefold() for marker in page.markers if marker.polarity == "negative" and marker.tier <= 4} & negatives
            support = sorted(positive_input.keys() & grounded_positive)
            contradictions = sorted((positive_input.keys() & grounded_negative) | (absent_input.keys() & grounded_positive))
            if not support:
                if positive_input.keys() & positives:
                    warnings.append(f"{metadata['standard_name']}: no resolvable Marker evidence; candidate excluded.")
                continue
            species_match = context(request.species, metadata["species"], True)
            matching_contexts = [item for item in page.contexts if _key(item[0]) == _key(request.species)]
            tissue_values = [value for _, values, _ in matching_contexts for value in values] or metadata["tissues"]
            disease_values = [value for _, _, values in matching_contexts for value in values]
            matches = AnnotationContext.model_validate({"species": species_match, "tissue": context(request.tissue, tissue_values), "disease": context(request.disease, disease_values)})
            relevant = [marker for marker in page.markers if marker.tier <= 4 and (
                marker.polarity == "positive" and marker.gene.casefold() in grounded_positive & set(support + contradictions)
                or marker.polarity == "negative" and marker.gene.casefold() in grounded_negative
            )]
            tiers = [marker.tier for marker in relevant if marker.polarity == "positive"]
            parent_match = bool(request.cluster.parent_cell_type and _key(request.cluster.parent_cell_type) == _key(metadata.get("parent_type") or ""))
            rank = (-len(support), len(contradictions), -sum(value == "matched" for value in matches.model_dump().values()), -int(parent_match), max(tiers))
            weak = bool(contradictions or metadata["conflicts"] or any(value in {"cross_context", "mismatched"} for value in matches.model_dump().values()) or max(tiers) > 3)
            level: Literal["strong", "moderate", "weak"] = "weak" if weak else "strong" if len(support) >= 2 and species_match == "matched" and matches.tissue == "matched" else "moderate"
            candidate = AnnotationCandidate(
                candidate_id=metadata["standard_name"], standard_name=metadata["standard_name"],
                display_name=metadata["display_name"], aliases=metadata["aliases"],
                parent_type=metadata.get("parent_type"), ontology_id=metadata.get("cl_id"),
                support_level=level, supporting_markers=[positive_input[value] for value in support],
                expected_absent_markers=[value for value in metadata["negative_markers"] if value.casefold() in grounded_negative],
                contradictory_markers=[positive_input[value] if value in positive_input else absent_input[value] for value in contradictions],
                context_match=matches, rationale=f"Wiki supports {len(support)} supplied positive markers; {len(contradictions)} marker contradictions. Support level is an uncalibrated heuristic.",
                evidence_ids=[],
            )
            ranked.append((rank, candidate, page, relevant))
        ranked.sort(key=lambda item: (item[0], item[1].standard_name))
        ambiguous = bool(ranked and (ranked[0][1].support_level == "weak" or (len(ranked) > 1 and ranked[0][0] == ranked[1][0])))
        selected = ranked[:request.max_candidates]
        evidence: list[AnnotationEvidence] = []
        for _, candidate, page, relevant in selected:
            if ambiguous:
                candidate.support_level = "weak"
            for dimension, value in candidate.context_match.model_dump().items():
                if value in {"cross_context", "mismatched"}:
                    warnings.append(f"{candidate.candidate_id}: {dimension} {value}.")
            if page.metadata["conflicts"]:
                warnings.append(f"{candidate.candidate_id}: Wiki records unresolved conflicts.")
            for marker in relevant:
                reference = page.references[marker.paper_id]
                evidence_id = f"E{len(evidence) + 1}"
                candidate.evidence_ids.append(evidence_id)
                def optional(field: str) -> str | None:
                    value = reference.get(field)
                    return value.strip() if isinstance(value, str) and value.strip() else None
                if optional("title") is None:
                    warnings.append(f"{marker.paper_id}: bibliographic metadata is not explicitly bound; title may be unavailable.")
                evidence.append(AnnotationEvidence(
                    evidence_id=evidence_id, evidence_tier=marker.tier,
                    claim=f"{page.metadata['display_name']}: Wiki reports {marker.gene} as a {marker.polarity} marker.",
                    paper_id=marker.paper_id, title=optional("title"), doi=optional("doi"), url=optional("url"),
                    page_path=page.path, locator=f"{page.path}:L{marker.line}",
                ))
        candidates = [item[1] for item in selected]
        return AnnotationResponse(
            request_id=request.request_id, status="no_match" if not ranked else "ambiguous" if ambiguous else "matched",
            recommendation=candidates[0] if candidates and not ambiguous else None,
            alternative_candidates=candidates if ambiguous else candidates[1:], evidence=evidence,
            warnings=sorted(set(warnings)), knowledge_version=version,
        )
