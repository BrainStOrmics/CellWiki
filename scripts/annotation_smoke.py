"""End-to-end smoke check for the CellWiki annotation evidence API.

Starts the local daemon for a workspace when it is not running, sends one
real annotation query, validates the response contract, and reports a
PASS/FAIL checklist. The daemon is stopped again when this script started
it. Nothing in the workspace is modified beyond the daemon's own runtime
directory.

Usage:

    python scripts/annotation_smoke.py --workspace D:\\kb
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))

import annotation_client  # noqa: E402
from annotation_client import AnnotationError  # noqa: E402

LOCATOR_PATTERN = re.compile(r"^.+\.md:L\d+$")
SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")


def _read_frontmatter_list(text: str, field: str) -> list[str]:
    match = re.search(rf"^{field}:\s*\[([^\]]*)\]\s*$", text, re.MULTILINE)
    if not match:
        return []
    return [item.strip().strip("\"'") for item in match.group(1).split(",") if item.strip()]


def derive_query(workspace: Path) -> dict[str, Any]:
    """Derive a plausible query from the first cell type page of a workspace."""
    pages = sorted((workspace / "wiki" / "cell_types").glob("*.md"))
    if not pages:
        raise SystemExit(f"no wiki/cell_types/*.md under {workspace}; nothing to query")
    text = pages[0].read_text(encoding="utf-8", errors="replace")
    markers = _read_frontmatter_list(text, "positive_markers")
    if not markers:
        markers = [
            row.split("|")[1].strip().removeprefix("[[").removesuffix("]]")
            for row in text.splitlines()
            if row.startswith("| [[")
        ][:3]
    species = _read_frontmatter_list(text, "species")
    tissues = _read_frontmatter_list(text, "tissues")
    if not markers:
        raise SystemExit(f"cannot read markers from {pages[0]}")
    return {
        "species": species[0] if species else "Homo sapiens",
        "tissue": tissues[0] if tissues else "blood",
        "markers": markers[:3],
        "page": pages[0].relative_to(workspace).as_posix(),
    }


def daemon_state(workspace: Path, *, runner: Callable[..., Any] = subprocess.run) -> dict:
    completed = runner(
        annotation_client.daemon_command(str(workspace)),
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if completed.returncode != 0:
        return {"state": "absent"}
    try:
        return json.loads(completed.stdout)
    except ValueError:
        return {"state": "unknown"}


def start_daemon(workspace: Path) -> None:
    command = annotation_client.daemon_command(str(workspace))
    serve = command[:1] + ["serve", "--workspace", str(workspace), "--detach"]
    completed = subprocess.run(serve, capture_output=True, text=True, timeout=120, check=False)
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()[:300]
        raise SystemExit(f"cannot start the CellWiki daemon: {detail}")


def stop_daemon(workspace: Path) -> None:
    command = annotation_client.daemon_command(str(workspace))
    stop = command[:1] + ["stop", "--workspace", str(workspace)]
    subprocess.run(stop, capture_output=True, text=True, timeout=60, check=False)


def check_response(response: dict[str, Any]) -> list[tuple[str, bool, str]]:
    """Validate the documented response contract."""
    checks: list[tuple[str, bool, str]] = []
    status = response.get("status")
    checks.append((
        "status is a documented value",
        status in {"matched", "ambiguous", "no_match"},
        f"status={status!r}",
    ))
    recommendation = response.get("recommendation")
    checks.append((
        "recommendation present only for a matched answer",
        (recommendation is not None) == (status == "matched"),
        f"recommendation={'yes' if recommendation else 'no'}",
    ))
    evidence = response.get("evidence") or []
    evidence_ids = {item.get("evidence_id") for item in evidence}
    candidates = ([recommendation] if recommendation else []) + list(
        response.get("alternative_candidates") or []
    )
    dangling = sorted({
        reference
        for candidate in candidates
        for reference in candidate.get("evidence_ids", [])
        if reference not in evidence_ids
    })
    checks.append((
        "every evidence_ids entry resolves",
        not dangling,
        f"dangling={dangling}" if dangling else f"{len(evidence_ids)} ids",
    ))
    missing_locators = [
        item.get("evidence_id")
        for item in evidence
        if not item.get("paper_id")
        or not LOCATOR_PATTERN.match(str(item.get("locator") or ""))
    ]
    checks.append((
        "evidence carries a paper and a page locator",
        not missing_locators,
        f"missing={missing_locators}" if missing_locators else f"{len(evidence)} entries",
    ))
    bad_tiers = [
        item.get("evidence_id")
        for item in evidence
        if not isinstance(item.get("evidence_tier"), int)
        or not 1 <= int(item["evidence_tier"]) <= 5
    ]
    checks.append((
        "evidence tiers are within Tier 1-5",
        not bad_tiers,
        f"bad={bad_tiers}" if bad_tiers else "ok",
    ))
    scored = [
        candidate.get("candidate_id")
        for candidate in candidates
        if candidate.get("support_score") is not None
    ]
    checks.append((
        "support_score stays null",
        not scored,
        f"scored={scored}" if scored else "null everywhere",
    ))
    version = str(response.get("knowledge_version") or "")
    checks.append((
        "knowledge_version is a commit sha",
        bool(SHA_PATTERN.match(version)),
        version[:12] or "missing",
    ))
    warnings = response.get("warnings")
    checks.append((
        "warnings is a list of strings",
        isinstance(warnings, list)
        and all(isinstance(item, str) for item in warnings),
        f"{len(warnings) if isinstance(warnings, list) else '?'} warnings",
    ))
    return checks


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--base-url", default=None)
    parser.add_argument("--token", default=None)
    parser.add_argument("--species", default=None)
    parser.add_argument("--tissue", default=None)
    parser.add_argument("--markers", default=None, help="Comma separated markers.")
    parser.add_argument("--keep-daemon", action="store_true")
    parser.add_argument("--json", action="store_true", help="Print the raw response JSON.")
    arguments = parser.parse_args(argv)

    workspace = arguments.workspace.expanduser().resolve()
    if not workspace.is_dir():
        raise SystemExit(f"workspace {workspace} does not exist")
    derived = derive_query(workspace)
    species = arguments.species or derived["species"]
    tissue = arguments.tissue or derived["tissue"]
    markers = (
        annotation_client.split_markers(arguments.markers)
        if arguments.markers
        else derived["markers"]
    )

    started = False
    state = daemon_state(workspace)
    if state.get("state") != "running":
        start_daemon(workspace)
        started = True
        state = daemon_state(workspace)
        if state.get("state") != "running":
            raise SystemExit(f"the CellWiki daemon did not start: {state}")
    print(f"workspace: {workspace}")
    print(f"daemon:    127.0.0.1:{state.get('port')} (pid {state.get('pid')})")
    print(f"query:     species={species} tissue={tissue} markers={','.join(markers)}")
    try:
        response = annotation_client.cellwiki_query(
            species=species,
            tissue=tissue,
            top_markers=markers,
            workspace=str(workspace),
            base_url=arguments.base_url,
            token=arguments.token,
            request_id="annotation-smoke",
        )
    except AnnotationError as error:
        print(f"query failed: {error.code}: {error.message}", file=sys.stderr)
        if started and not arguments.keep_daemon:
            stop_daemon(workspace)
        return 1

    checks = check_response(response)
    if arguments.json:
        print(json.dumps(response, ensure_ascii=False, indent=2))
    for name, passed, detail in checks:
        print(f"[{'PASS' if passed else 'FAIL'}] {name} ({detail})")
    failed = [name for name, passed, _ in checks if not passed]
    print(f"\nstatus: {response.get('status')} | knowledge_version: {response.get('knowledge_version')}")
    recommendation = response.get("recommendation")
    if recommendation:
        print(
            f"recommendation: {recommendation.get('candidate_id')} "
            f"({recommendation.get('support_level')})"
        )
    if started and not arguments.keep_daemon:
        stop_daemon(workspace)
        print("daemon: stopped (it was started by this script)")
    if failed:
        print(f"RESULT: FAIL ({len(failed)} checks failed)")
        return 1
    print("RESULT: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
