"""BFCL multi_turn calibration adapter (isolated environment; opt-in).

Drives the Berkeley Function-Call Leaderboard (BFCL) in a SEPARATE checkout
and interpreter via subprocess. BFCL is never added to the main project
dependencies; its checkout and virtualenv live under ``build/`` (gitignored).

Pin: gorilla commit 6ea57973c7a6097fd7c5915698c54c17c5b1b6c8, multi_turn
categories only. The report carries ``track = "bfcl"`` and is never merged
into CellWiki pass^k. Without a BFCL environment the report is ``partial``;
scores are never fabricated.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from cellwiki.evaluation.agent_eval_v2 import RUNS_DIR

BFCL_PIN_COMMIT = "6ea57973c7a6097fd7c5915698c54c17c5b1b6c8"
BFCL_PIN_SHORT = BFCL_PIN_COMMIT[:7]
BFCL_MULTI_TURN_CATEGORIES = [
    "multi_turn_base",
    "multi_turn_miss_func",
    "multi_turn_miss_param",
    "multi_turn_long_context",
]
BFCL_REPO_URL = "https://github.com/ShishirPatil/gorilla.git"
DEFAULT_CHECKOUT_ROOT = Path("build") / "bfcl" / f"gorilla-{BFCL_PIN_SHORT}"

EXIT_OK = 0
EXIT_PARTIAL = 1


def build_bfcl_commands(bfcl_bin: str, model: str, category: str) -> list[list[str]]:
    """The exact generate/evaluate invocations; recorded in the report."""

    return [
        [bfcl_bin, "generate", "--model", model, "--test-category", category, "--num-threads", "1"],
        [bfcl_bin, "evaluate", "--model", model, "--test-category", category],
    ]


def resolve_categories(category: str) -> list[str]:
    """``multi_turn`` expands to the four official sub-categories."""

    if category != "multi_turn":
        return [category]
    return list(BFCL_MULTI_TURN_CATEGORIES)


def git_head(root: Path) -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=str(root),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"git rev-parse failed in {root}: {completed.stderr.strip()[:200]}")
    return completed.stdout.strip()


def verify_pin(root: Path) -> str:
    """Return the checkout HEAD; refuse to run against any other commit."""

    head = git_head(root)
    if head != BFCL_PIN_COMMIT:
        raise RuntimeError(
            f"BFCL checkout at {root} is {head}, but the pin is {BFCL_PIN_COMMIT}"
        )
    return head


def setup_checkout(target: Path) -> Path:
    """Clone gorilla and checkout the pinned commit (network; opt-in)."""

    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["git", "clone", BFCL_REPO_URL, str(target)],
            check=True,
            capture_output=True,
            text=True,
            timeout=1800,
        )
    subprocess.run(
        ["git", "-C", str(target), "checkout", BFCL_PIN_COMMIT],
        check=True,
        capture_output=True,
        text=True,
        timeout=120,
    )
    return target


def collect_raw_artifacts(bfcl_root: Path, model: str, out_dir: Path) -> list[str]:
    """Copy raw BFCL result/score files for evidence (bounded set)."""

    copied: list[str] = []
    raw_dir = out_dir / "raw"
    for sub_name in ("result", "score"):
        base = bfcl_root / sub_name / model
        if not base.is_dir():
            continue
        for file_path in sorted(base.rglob("*")):
            if not file_path.is_file():
                continue
            relative = file_path.relative_to(bfcl_root)
            target = raw_dir / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(file_path, target)
            copied.append(relative.as_posix())
            if len(copied) >= 200:
                return copied
    return copied


def write_report(
    out_dir: Path,
    *,
    status: str,
    reason: str | None,
    model: str | None,
    categories: list[str],
    bfcl_root: str | None = None,
    head_commit: str | None = None,
    commands: list[list[str]] | None = None,
    artifacts: list[str] | None = None,
) -> Path:
    """Persist the independent BFCL report; track stays ``bfcl`` forever."""

    report = {
        "track": "bfcl",
        "bfcl_pin_commit": BFCL_PIN_COMMIT,
        "bfcl_head_commit": head_commit,
        "bfcl_root": bfcl_root,
        "categories": categories,
        "model_config": model,
        "commands": commands or [],
        "status": status,
        "not_executed_reason": reason,
        "artifacts": artifacts or [],
        "generated_at": datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ"),
        "note": (
            "BFCL scores answer 'how strong is the underlying model at "
            "multi-turn function calling'; they never validate CellWiki "
            "runtime, tool contracts, or the approval chain."
        ),
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "report.json"
    path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", help="BFCL model config name (e.g. openai-compat-...)")
    parser.add_argument(
        "--category",
        default="multi_turn",
        help="multi_turn (default) expands to the four official sub-categories",
    )
    parser.add_argument(
        "--bfcl-root",
        type=Path,
        help="Existing gorilla checkout at the pinned commit (default: build/bfcl/...)",
    )
    parser.add_argument(
        "--setup",
        action="store_true",
        help="Clone gorilla and checkout the pin into build/ (network).",
    )
    parser.add_argument(
        "--bfcl-bin",
        default="bfcl",
        help="bfcl executable inside the isolated environment (default: bfcl on PATH)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the planned commands and write a planned/partial report.",
    )
    parser.add_argument("--out-dir", type=Path)
    args = parser.parse_args()

    categories = resolve_categories(args.category)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out_dir = args.out_dir or RUNS_DIR / stamp / "bfcl"

    if args.dry_run:
        commands = build_bfcl_commands(args.bfcl_bin, args.model or "<model>", args.category)
        for command in commands:
            print("[bfcl dry-run]", " ".join(command))
        path = write_report(
            out_dir,
            status="planned",
            reason="dry_run",
            model=args.model,
            categories=categories,
            commands=commands,
        )
        print(f"report: {path}")
        return EXIT_OK

    if not args.model:
        parser.error("--model is required without --dry-run")

    bfcl_root = args.bfcl_root or DEFAULT_CHECKOUT_ROOT
    if args.setup:
        bfcl_root = setup_checkout(bfcl_root)
        print(f"[bfcl] checkout ready at {bfcl_root}")

    try:
        head = verify_pin(bfcl_root)
    except (RuntimeError, OSError) as error:
        print(f"[bfcl] pin verification failed: {error}")
        write_report(
            out_dir,
            status="partial",
            reason="pin_verification_failed",
            model=args.model,
            categories=categories,
            bfcl_root=str(bfcl_root),
        )
        return EXIT_PARTIAL

    all_commands: list[list[str]] = []
    for sub_category in categories:
        for command in build_bfcl_commands(args.bfcl_bin, args.model, sub_category):
            all_commands.append(command)
            print("[bfcl run]", " ".join(command), flush=True)
            completed = subprocess.run(
                command,
                cwd=str(bfcl_root),
                timeout=7200,
            )
            if completed.returncode != 0:
                print(f"[bfcl] command failed with exit code {completed.returncode}")
                write_report(
                    out_dir,
                    status="partial",
                    reason=f"command_failed:{command[1]}:{sub_category}",
                    model=args.model,
                    categories=categories,
                    bfcl_root=str(bfcl_root),
                    head_commit=head,
                    commands=all_commands,
                )
                return EXIT_PARTIAL

    artifacts = collect_raw_artifacts(bfcl_root, args.model, out_dir)
    write_report(
        out_dir,
        status="completed",
        reason=None,
        model=args.model,
        categories=categories,
        bfcl_root=str(bfcl_root),
        head_commit=head,
        commands=all_commands,
        artifacts=artifacts,
    )
    print(f"[bfcl] completed; report: {out_dir / 'report.json'}")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
