"""Reference client for the CellWiki annotation evidence API.

Standalone on purpose: this file uses the standard library only so that an
integrator can copy it into another project without pulling CellWiki in.
It never writes to the workspace, never calls a model provider, and only
reads knowledge the CellWiki side has already committed and approved.

Usage:

    python scripts/annotation_client.py --workspace D:\\kb \\
        --species "Homo sapiens" --tissue blood --markers CD4,IL7R
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Sequence

ANNOTATION_PATH = "/api/v1/annotation-support"
TOKEN_ENV = "CELLWIKI_ANNOTATION_API_TOKEN"
RETRYABLE_CODES = {"KNOWLEDGE_BUSY", "KNOWLEDGE_UNAVAILABLE", "INTERNAL_ERROR"}


class AnnotationError(RuntimeError):
    """The annotation service could not answer the request."""

    def __init__(self, code: str, message: str, *, status: int | None = None,
                 retryable: bool = False) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.status = status
        self.retryable = retryable


class AnnotationRequestError(AnnotationError):
    """The request was rejected; fix the payload instead of retrying."""


class AnnotationUnauthorizedError(AnnotationError):
    """The service token is missing or wrong."""


class AnnotationServiceDisabledError(AnnotationError):
    """The CellWiki side has not enabled the annotation API."""


class AnnotationBusyError(AnnotationError):
    """Knowledge is being updated or awaits approval; retry later."""


class AnnotationUnavailableError(AnnotationError):
    """Committed knowledge cannot be queried reliably right now."""


class AnnotationUnreachableError(AnnotationError):
    """The local service did not answer at all."""


def normalize_markers(values: Iterable[str]) -> list[str]:
    """Trim, drop blanks, and de-duplicate case-insensitively."""
    result: dict[str, str] = {}
    for value in values:
        symbol = value.strip()
        if symbol:
            result.setdefault(symbol.casefold(), symbol)
    return list(result.values())


def split_markers(text: str) -> list[str]:
    """Split a comma separated marker list."""
    return normalize_markers(part for part in text.replace(";", ",").split(","))


def build_payload(
    *,
    request_id: str,
    species: str,
    tissue: str,
    top_markers: Iterable[str],
    low_or_absent_markers: Iterable[str] = (),
    disease: str | None = None,
    cluster: dict[str, Any] | None = None,
    max_candidates: int = 3,
) -> dict[str, Any]:
    """Build the request body and enforce the documented input constraints."""
    positives = normalize_markers(top_markers)
    absent = normalize_markers(low_or_absent_markers)
    if not positives:
        raise ValueError("top_markers must contain at least one gene symbol")
    if not species.strip() or not tissue.strip():
        raise ValueError("species and tissue are required")
    overlap = {value.casefold() for value in positives} & {
        value.casefold() for value in absent
    }
    if overlap:
        raise ValueError(
            "a gene cannot be both a positive and a low/absent marker: "
            + ", ".join(sorted(overlap))
        )
    if not 1 <= max_candidates <= 5:
        raise ValueError("max_candidates must be between 1 and 5")
    return {
        "request_id": request_id,
        "species": species,
        "tissue": tissue,
        "disease": disease,
        "cluster": cluster or {"id": request_id},
        "top_markers": positives,
        "low_or_absent_markers": absent,
        "max_candidates": max_candidates,
    }


def daemon_command(workspace: str) -> list[str]:
    """Build the command that reports the local daemon state."""
    executable = shutil.which("cellwiki")
    if executable:
        return [executable, "daemon", "status", "--workspace", workspace]
    return [
        sys.executable, "-m", "cellwiki.product_cli",
        "daemon", "status", "--workspace", workspace,
    ]


def daemon_port(
    workspace: str,
    *,
    runner: Callable[..., Any] = subprocess.run,
) -> int:
    """Read the loopback port of the local daemon that serves a workspace."""
    completed = runner(
        daemon_command(workspace),
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()[:300]
        raise AnnotationUnreachableError(
            "DAEMON_UNAVAILABLE",
            f"cannot read the daemon state for {workspace}: {detail}",
        )
    try:
        payload = json.loads(completed.stdout)
    except ValueError as error:
        raise AnnotationUnreachableError(
            "DAEMON_UNAVAILABLE", f"unexpected daemon state: {error}"
        ) from None
    state = payload.get("state")
    if state != "running" or "port" not in payload:
        raise AnnotationUnreachableError(
            "DAEMON_UNAVAILABLE",
            f"the CellWiki daemon for {workspace} is not running (state={state!r}); "
            f"start it with 'cellwiki serve --workspace {workspace} --detach'",
        )
    return int(payload["port"])


@dataclass(frozen=True)
class _Reply:
    status: int
    body: str
    retry_after: float | None = None


def _decode(payload: bytes) -> str:
    return payload.decode("utf-8", errors="replace")


def _post(
    base_url: str,
    token: str,
    payload: dict[str, Any],
    *,
    timeout: float,
    opener: Callable[..., Any],
) -> _Reply:
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}{ANNOTATION_PATH}",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": f"Bearer {token}",
        },
        method="POST",
    )
    try:
        with opener(request, timeout=timeout) as response:
            return _Reply(
                status=int(getattr(response, "status", 200)),
                body=_decode(response.read()),
            )
    except urllib.error.HTTPError as error:
        headers = getattr(error, "headers", None)
        retry_after = None
        if headers is not None:
            raw = headers.get("Retry-After")
            if raw:
                try:
                    retry_after = float(raw)
                except ValueError:
                    retry_after = None
        return _Reply(
            status=int(error.code),
            body=_decode(error.read() or b""),
            retry_after=retry_after,
        )
    except urllib.error.URLError as error:
        raise AnnotationUnreachableError(
            "SERVICE_UNREACHABLE", f"cannot reach the CellWiki service: {error.reason}"
        ) from None


def _error_from(status: int, body: str) -> AnnotationError:
    code, message, retryable = "INTERNAL_ERROR", body[:300], status >= 500
    try:
        parsed = json.loads(body)
        error = parsed.get("error", {}) if isinstance(parsed, dict) else {}
        if isinstance(error, dict):
            code = str(error.get("code") or code)
            message = str(error.get("message") or message)
            retryable = bool(error.get("retryable", retryable))
    except ValueError:
        pass
    if status == 400:
        return AnnotationRequestError(code, message, status=status, retryable=False)
    if status == 401:
        return AnnotationUnauthorizedError(code, message, status=status, retryable=False)
    if code == "SERVICE_DISABLED":
        return AnnotationServiceDisabledError(code, message, status=status, retryable=False)
    if code == "KNOWLEDGE_BUSY":
        return AnnotationBusyError(code, message, status=status, retryable=True)
    if code == "KNOWLEDGE_UNAVAILABLE":
        return AnnotationUnavailableError(code, message, status=status, retryable=True)
    return AnnotationError(code, message, status=status, retryable=retryable)


def query_evidence(
    base_url: str,
    token: str,
    payload: dict[str, Any],
    *,
    timeout: float = 60.0,
    max_attempts: int = 3,
    opener: Callable[..., Any] = urllib.request.urlopen,
    sleeper: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """Send one annotation query and return the parsed response.

    Retries only the failures a caller can survive: a busy knowledge base, an
    unreliable snapshot, and a transient server error. A rejected request or a
    wrong token is raised immediately.
    """
    attempts = max(1, max_attempts)
    for attempt in range(1, attempts + 1):
        reply = _post(base_url, token, payload, timeout=timeout, opener=opener)
        if reply.status == 200:
            try:
                parsed = json.loads(reply.body)
            except ValueError as error:
                raise AnnotationError(
                    "INVALID_RESPONSE", f"the service returned invalid JSON: {error}",
                    status=reply.status,
                ) from None
            if not isinstance(parsed, dict):
                raise AnnotationError(
                    "INVALID_RESPONSE", "the service returned a non-object body",
                    status=reply.status,
                )
            return parsed
        error = _error_from(reply.status, reply.body)
        if not error.retryable or error.code not in RETRYABLE_CODES:
            raise error
        if attempt >= attempts:
            raise error
        delay = (
            reply.retry_after
            if reply.retry_after is not None
            else min(2.0 ** attempt, 10.0)
        )
        sleeper(delay)
    raise AnnotationError("INTERNAL_ERROR", "unreachable retry state")


def cellwiki_query(
    *,
    species: str,
    tissue: str,
    top_markers: Iterable[str],
    workspace: str | None = None,
    base_url: str | None = None,
    token: str | None = None,
    low_or_absent_markers: Iterable[str] = (),
    disease: str | None = None,
    cluster: dict[str, Any] | None = None,
    max_candidates: int = 3,
    request_id: str = "annotation-request",
    timeout: float = 60.0,
    max_attempts: int = 3,
) -> dict[str, Any]:
    """Resolve the endpoint, then query it."""
    resolved_token = token or os.getenv(TOKEN_ENV, "")
    if not resolved_token:
        raise AnnotationUnauthorizedError(
            "MISSING_TOKEN", f"set {TOKEN_ENV} or pass an explicit token"
        )
    if base_url is None:
        if workspace is None:
            raise ValueError("pass either workspace or base_url")
        base_url = f"http://127.0.0.1:{daemon_port(workspace)}"
    payload = build_payload(
        request_id=request_id,
        species=species,
        tissue=tissue,
        top_markers=top_markers,
        low_or_absent_markers=low_or_absent_markers,
        disease=disease,
        cluster=cluster,
        max_candidates=max_candidates,
    )
    return query_evidence(
        base_url,
        resolved_token,
        payload,
        timeout=timeout,
        max_attempts=max_attempts,
    )


def summarize(response: dict[str, Any]) -> str:
    """Render a short human readable summary of an annotation response."""
    lines = [
        f"status: {response.get('status')}",
        f"knowledge_version: {response.get('knowledge_version')}",
    ]
    recommendation = response.get("recommendation")
    if recommendation:
        lines.append(
            "recommendation: {id} ({level}) support={support} contradictions={contra}".format(
                id=recommendation.get("candidate_id"),
                level=recommendation.get("support_level"),
                support=",".join(recommendation.get("supporting_markers", [])) or "-",
                contra=",".join(recommendation.get("contradictory_markers", [])) or "-",
            )
        )
    alternatives = response.get("alternative_candidates") or []
    if alternatives:
        lines.append(
            "alternatives: "
            + ", ".join(
                f"{item.get('candidate_id')}({item.get('support_level')})"
                for item in alternatives
            )
        )
    evidence = response.get("evidence") or []
    lines.append(f"evidence: {len(evidence)}")
    for item in evidence[:5]:
        lines.append(
            f"  - {item.get('evidence_id')} tier={item.get('evidence_tier')} "
            f"{item.get('paper_id')} {item.get('locator')}"
        )
    warnings = response.get("warnings") or []
    if warnings:
        lines.append(f"warnings: {len(warnings)}")
        for warning in warnings[:5]:
            lines.append(f"  - {warning}")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", help="Knowledge-base workspace served by the local daemon.")
    parser.add_argument("--base-url", help="Endpoint base URL; overrides --workspace discovery.")
    parser.add_argument("--token", default=None, help=f"Service token (default: ${TOKEN_ENV}).")
    parser.add_argument("--species", required=True)
    parser.add_argument("--tissue", required=True)
    parser.add_argument("--disease", default=None)
    parser.add_argument("--markers", required=True, help="Comma separated positive markers.")
    parser.add_argument("--absent", default="", help="Comma separated low/absent markers.")
    parser.add_argument("--parent-cell-type", default=None)
    parser.add_argument("--current-cell-type", default=None)
    parser.add_argument("--request-id", default="annotation-request")
    parser.add_argument("--max-candidates", type=int, default=3)
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--max-attempts", type=int, default=3)
    parser.add_argument("--json", action="store_true", help="Print the raw response JSON.")
    arguments = parser.parse_args(argv)

    cluster: dict[str, Any] = {"id": arguments.request_id}
    if arguments.parent_cell_type:
        cluster["parent_cell_type"] = arguments.parent_cell_type
    if arguments.current_cell_type:
        cluster["current_cell_type"] = arguments.current_cell_type
    try:
        response = cellwiki_query(
            species=arguments.species,
            tissue=arguments.tissue,
            top_markers=split_markers(arguments.markers),
            low_or_absent_markers=split_markers(arguments.absent),
            disease=arguments.disease,
            cluster=cluster,
            max_candidates=arguments.max_candidates,
            request_id=arguments.request_id,
            timeout=arguments.timeout,
            max_attempts=arguments.max_attempts,
            workspace=arguments.workspace,
            base_url=arguments.base_url,
            token=arguments.token,
        )
    except AnnotationError as error:
        print(f"error {error.code}: {error.message}", file=sys.stderr)
        return 1
    if arguments.json:
        print(json.dumps(response, ensure_ascii=False, indent=2))
    else:
        print(summarize(response))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
