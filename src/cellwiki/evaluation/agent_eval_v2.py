# =============================================================================
# Agent 多轮评测体系 v2 —— 旁路于 v1 的评测引擎
# =============================================================================
# 设计提案：design/active/2026-09-13-agent-evaluation-system-v2.md；实施计划：
# docs/process/plans/2026-09-13-agent-evaluation-system-v2.md。v1（evals/agent/
# 与 agent_eval.py）保持原样；本模块只服务 evals/agent_v2/。
#
# 分层：
#   * 纯确定性部分 —— suite 加载与 schema 校验、fixture 准备、断言执行、
#     打分、pass_1/pass^3 与 baseline diff。无网络、无模型调用，可在无
#     API Key 环境进入 CI。
#   * 编排部分 —— ScenarioRunner 直接驱动 AgentRuntimeManager 执行多轮
#     scenario。runner 自身不构造任何模型客户端：真实模型运行由
#     scripts/run_agent_eval_v2.py 以"无 adapter"的 manager 注入产品图；
#     oracle 重放与负向变异注入 evals/agent_v2/ 下的脚本模块。因此本模块
#     import 即离线，打分函数永远离线。
#
# 与 v1 的唯一复用点：cited_paths() 的引用提取口径，避免两套标准漂移。
# =============================================================================

"""Multi-turn Agent evaluation harness v2 (bypass track; v1 stays untouched)."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import fnmatch
import os
import posixpath
import shutil
import stat
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import Any, Callable, Iterable

from cellwiki.domain.pending_diff import PendingDiffStatus
from cellwiki.domain.runs import AgentEventType, AgentRunStatus, RunBudget
from cellwiki.domain.contracts import WikiAgentContext
from cellwiki.evaluation.agent_eval import cited_paths
from cellwiki.services.agent_runtime import (
    AgentRunInProgressError,
    AgentRuntimeManager,
    InvalidRunTransitionError,
    RuntimeSignal,
)
from cellwiki.services.git_executor import GitCommandError
from cellwiki.services.quality import inspect_projection
from cellwiki.services.workspace import ensure_workspace

HARNESS_VERSION = "agent-eval-v2/0.1.0"
SUPPORTED_SCHEMA_VERSION = 2
SUPPORTED_LAYERS = frozenset({"gate", "diagnostic", "sealed"})
STEP_ACTIONS = frozenset(
    {"send", "answer_question", "accept_diff", "reject_diff", "assert"}
)

# 固定主因枚举（交接文档）：失败归因只能落在这里，不能自由发挥。
FAILURE_CATEGORIES = frozenset(
    {
        "intent",
        "retrieval",
        "tool_selection",
        "tool_arguments",
        "state_carryover",
        "approval",
        "grounding",
        "content",
        "termination",
        "budget",
        "safety",
        "infrastructure",
        "evaluator",
    }
)

# ADR-0009：四个系统维护文件。Agent 的写尝试是安全信号，系统自己的维护
# 写入不算 Agent 的改动面。
SYSTEM_OWNED_FILES = frozenset(
    {"overview.md", "statistics.md", "log.md", "audit_report.md"}
)
# 与 v1 保持一致的写工具集合：write_calls 证据从 TOOL_STARTED 事件提取。
WRITE_TOOLS = frozenset({"write_file", "edit_file", "delete_file", "rename_file"})

# 与运行时门禁同一口径：L1 警告不阻塞，只有 L0 错误算 lint 失败。
LINT_PASS_STATUSES = frozenset({"passed", "passed_with_warnings"})

# run 终态集合：send/answer_question 等动作要等到这些状态才能继续。
TERMINAL_RUN_STATUSES = frozenset(
    {
        AgentRunStatus.SUCCEEDED,
        AgentRunStatus.REJECTED,
        AgentRunStatus.FAILED,
        AgentRunStatus.UNFINISHED,
        AgentRunStatus.CANCELLED,
        AgentRunStatus.WAITING_APPROVAL,
    }
)

REPO_ROOT = Path(__file__).resolve().parents[3]
EVALS_V2_ROOT = REPO_ROOT / "evals" / "agent_v2"
SUITES_DIR = EVALS_V2_ROOT / "suites"
ORACLES_DIR = EVALS_V2_ROOT / "oracles"
MUTATIONS_DIR = EVALS_V2_ROOT / "mutations"
RUNS_DIR = EVALS_V2_ROOT / "runs"

# suite 里 fixture 字段自带 "fixtures/<name>" 前缀（与 oracle/mutations 的
# 相对路径口径一致），因此解析基准是 EVALS_V2_ROOT 而不是 fixtures 目录。


def fixture_workspace_dir(fixture: str) -> Path:
    return EVALS_V2_ROOT / fixture / "workspace"

# evals/agent_v2/runs/ 只保存本地运行产物，永不入库（见 .gitignore 与 README）。
DEFAULT_WORKSPACE_BUILD_ROOT = REPO_ROOT / "build" / "agent-v2-eval"

# 一次 trial 内，单个 run 最多自动应答多少次意外提问（固定脚本用户政策）。
MAX_AUTO_ANSWERS_PER_RUN = 2

# 每步在 run 自身预算之外的等待宽限：run 的墙钟预算由产品运行时强制，
# 这里只兜底"运行时自己卡死"的极端情况，超时按 infrastructure 记录。
STEP_WAIT_GRACE_SECONDS = 120.0

_ASSERTION_TYPE_FIELDS: dict[str, dict[str, Any]] = {
    # type -> {"required": [...], "optional": {...}}
    "file_exists": {"required": ("path",), "optional": set()},
    "file_not_exists": {"required": ("path",), "optional": set()},
    "file_contains": {
        "required": ("path",),
        "optional": {"text", "any_of", "all_of"},
    },
    "file_not_contains": {"required": ("path",), "optional": {"text", "any_of"}},
    "link_resolves": {"required": ("path", "link"), "optional": set()},
    "changed_paths_subset": {
        "required": ("allowed",),
        "optional": {"scope"},
    },
    "answer_contains": {"required": (), "optional": {"text", "any_of"}},
    "answer_not_contains": {"required": (), "optional": {"text", "any_of"}},
    "citation_exists": {"required": ("path",), "optional": set()},
    "no_unresolved_citations": {"required": (), "optional": set()},
    "terminal_status_in": {"required": ("statuses",), "optional": set()},
    "lint_passed": {"required": (), "optional": set()},
    "max_model_calls": {"required": ("limit",), "optional": {"scope"}},
    "no_system_file_write_attempts": {"required": (), "optional": set()},
    "git_tool_used": {"required": (), "optional": {"scope"}},
    "committed_since_snapshot": {"required": (), "optional": set()},
}

_SUITE_FIELDS = {
    "schema_version",
    "suite_id",
    "suite_version",
    "layer",
    "includes",
    "question_policy",
    "scenarios",
}
_SCENARIO_FIELDS = {
    "scenario_id",
    "kind",
    "tags",
    "fixture",
    "budget",
    "steps",
    "oracle",
    "mutations",
    "question_policy",
}
_STEP_FIELDS = {
    "send": {"action", "message"},
    "answer_question": {"action", "answers"},
    "accept_diff": {"action", "diff_id"},
    "reject_diff": {"action", "diff_id"},
    "assert": {"action", "assertions"},
}
_QUESTION_POLICY_FIELDS = {"mode", "answers", "max_answers_per_run"}


class SuiteValidationError(ValueError):
    """Raised when a suite file violates the v2 schema, before any model call."""


# ---------------------------------------------------------------------------
# suite 加载与 schema 校验
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Scenario:
    """One validated scenario; ``raw`` keeps the original mapping for reports."""

    scenario_id: str
    kind: str
    tags: tuple[str, ...]
    fixture: str
    budget: dict[str, int]
    steps: tuple[dict[str, Any], ...]
    oracle: str
    mutations: tuple[str, ...]
    question_policy: dict[str, Any] | None
    raw: dict[str, Any]


@dataclass(frozen=True)
class Suite:
    """A validated suite; scenarios of diagnostic suites include gate content."""

    suite_id: str
    suite_version: int
    layer: str
    question_policy: dict[str, Any] | None
    scenarios: tuple[Scenario, ...]
    path: Path
    source_hash: str

    def scenario(self, scenario_id: str) -> Scenario:
        for scenario in self.scenarios:
            if scenario.scenario_id == scenario_id:
                return scenario
        raise KeyError(f"unknown scenario in {self.suite_id}: {scenario_id}")


def _validate_assertion(assertion: Any, where: str, errors: list[str]) -> None:
    if not isinstance(assertion, dict):
        errors.append(f"{where}: assertion must be an object")
        return
    unknown = set(assertion) - {"type"}
    spec = _ASSERTION_TYPE_FIELDS.get(str(assertion.get("type")))
    if spec is None:
        errors.append(f"{where}: unknown assertion type {assertion.get('type')!r}")
        return
    assert isinstance(spec, dict)
    unknown -= set(spec["required"]) | set(spec["optional"])
    if unknown:
        errors.append(f"{where}: unknown assertion fields {sorted(unknown)}")
    for key in spec["required"]:
        value = assertion.get(key)
        if value is None or (isinstance(value, str) and not value.strip()):
            errors.append(f"{where}: assertion {assertion['type']} needs {key!r}")
    for key in ("text", "any_of", "all_of"):
        if key in assertion:
            value = assertion[key]
            if isinstance(value, str):
                if not value.strip():
                    errors.append(f"{where}: assertion {key} must be non-empty")
            elif isinstance(value, list):
                if not value or not all(
                    isinstance(item, str) and item.strip() for item in value
                ):
                    errors.append(f"{where}: assertion {key} must be non-empty strings")
            else:
                errors.append(f"{where}: assertion {key} must be str or list[str]")
    if assertion.get("type") == "changed_paths_subset":
        allowed = assertion.get("allowed")
        if not isinstance(allowed, list) or not all(
            isinstance(item, str) and item.strip() for item in allowed
        ):
            errors.append(f"{where}: 'allowed' must be a list of path patterns")
        scope = assertion.get("scope", "last_run")
        if scope not in {"last_run", "trial"}:
            errors.append(f"{where}: 'scope' must be 'last_run' or 'trial'")
    if assertion.get("type") == "max_model_calls":
        limit = assertion.get("limit")
        if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
            errors.append(f"{where}: 'limit' must be a positive integer")
        scope = assertion.get("scope", "last_run")
        if scope not in {"last_run", "trial"}:
            errors.append(f"{where}: 'scope' must be 'last_run' or 'trial'")
    if assertion.get("type") == "terminal_status_in":
        statuses = assertion.get("statuses")
        valid = {status.value for status in AgentRunStatus}
        if (
            not isinstance(statuses, list)
            or not statuses
            or not all(isinstance(item, str) and item in valid for item in statuses)
        ):
            errors.append(
                f"{where}: 'statuses' must be run status values from {sorted(valid)}"
            )


def _validate_text_field(
    step: dict[str, Any], key: str, where: str, errors: list[str]
) -> None:
    value = step.get(key)
    if isinstance(value, str) and value.strip():
        return
    if isinstance(value, list) and value and all(
        isinstance(item, str) and item.strip() for item in value
    ):
        return
    errors.append(f"{where}: {key!r} must be a non-empty string or list of strings")


def _validate_question_policy(policy: Any, where: str, errors: list[str]) -> None:
    if policy is None:
        return
    if not isinstance(policy, dict):
        errors.append(f"{where}: question_policy must be an object")
        return
    unknown = set(policy) - _QUESTION_POLICY_FIELDS
    if unknown:
        errors.append(f"{where}: unknown question_policy fields {sorted(unknown)}")
    mode = policy.get("mode", "answer")
    if mode not in {"answer", "fail"}:
        errors.append(f"{where}: question_policy.mode must be 'answer' or 'fail'")
    answers = policy.get("answers", [])
    if not isinstance(answers, list) or not all(
        isinstance(item, str) and item.strip() for item in answers
    ):
        errors.append(f"{where}: question_policy.answers must be a list of strings")
    max_answers = policy.get("max_answers_per_run", MAX_AUTO_ANSWERS_PER_RUN)
    if not isinstance(max_answers, int) or isinstance(max_answers, bool) or max_answers < 1:
        errors.append(f"{where}: question_policy.max_answers_per_run must be >= 1")


def _validate_scenario(scenario: Any, index: int, errors: list[str]) -> str | None:
    where = f"scenarios[{index}]"
    if not isinstance(scenario, dict):
        errors.append(f"{where}: scenario must be an object")
        return None
    unknown = set(scenario) - _SCENARIO_FIELDS
    if unknown:
        errors.append(f"{where}: unknown scenario fields {sorted(unknown)}")
    scenario_id = scenario.get("scenario_id")
    if not isinstance(scenario_id, str) or not scenario_id.strip():
        errors.append(f"{where}: scenario_id must be a non-empty string")
        return None
    where = f"scenarios[{scenario_id}]"
    for key in ("kind", "fixture"):
        value = scenario.get(key)
        if not isinstance(value, str) or not value.strip():
            errors.append(f"{where}: {key} must be a non-empty string")
    tags = scenario.get("tags")
    if not isinstance(tags, list) or not tags or not all(
        isinstance(item, str) and item.strip() for item in tags
    ):
        errors.append(f"{where}: tags must be a non-empty list of strings")
    budget = scenario.get("budget")
    if not isinstance(budget, dict):
        errors.append(f"{where}: budget must be an object")
    else:
        for key in ("max_model_calls", "max_tool_calls", "max_runtime_seconds"):
            value = budget.get(key)
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                errors.append(f"{where}: budget.{key} must be a positive integer")
    if not isinstance(scenario.get("fixture"), str) or not scenario.get("fixture"):
        return scenario_id
    fixture_workspace = fixture_workspace_dir(str(scenario["fixture"]))
    if not fixture_workspace.is_dir():
        errors.append(f"{where}: fixture workspace {scenario['fixture']!r} is missing")
    steps = scenario.get("steps")
    if not isinstance(steps, list) or not steps:
        errors.append(f"{where}: steps must be a non-empty list")
        return scenario_id
    for step_index, step in enumerate(steps):
        step_where = f"{where}.steps[{step_index}]"
        if not isinstance(step, dict):
            errors.append(f"{step_where}: step must be an object")
            continue
        action = step.get("action")
        if action not in STEP_ACTIONS:
            errors.append(f"{step_where}: unknown action {action!r}")
            continue
        allowed_fields = _STEP_FIELDS[str(action)]
        unknown = set(step) - allowed_fields
        if unknown:
            errors.append(f"{step_where}: unknown step fields {sorted(unknown)}")
        if action == "send":
            message = step.get("message")
            if not isinstance(message, str) or not message.strip():
                errors.append(f"{step_where}: send needs a non-empty message")
        elif action == "answer_question":
            _validate_text_field(step, "answers", step_where, errors)
        elif action == "assert":
            assertions = step.get("assertions")
            if not isinstance(assertions, list) or not assertions:
                errors.append(f"{step_where}: assert needs non-empty assertions")
                continue
            for assertion_index, assertion in enumerate(assertions):
                _validate_assertion(
                    assertion, f"{step_where}.assertions[{assertion_index}]", errors
                )
    oracle = scenario.get("oracle")
    if not isinstance(oracle, str) or not oracle.strip():
        errors.append(f"{where}: every formal scenario needs a replayable oracle")
    elif not (EVALS_V2_ROOT / oracle).is_file():
        errors.append(f"{where}: oracle file {oracle!r} does not exist")
    mutations = scenario.get("mutations", [])
    if not isinstance(mutations, list) or not all(
        isinstance(item, str) and item.strip() for item in mutations
    ):
        errors.append(f"{where}: mutations must be a list of script paths")
    else:
        for mutation in mutations:
            if not (EVALS_V2_ROOT / mutation).is_file():
                errors.append(f"{where}: mutation file {mutation!r} does not exist")
    _validate_question_policy(scenario.get("question_policy"), where, errors)
    return scenario_id


def _validate_suite_data(data: Any, origin: Path, errors: list[str]) -> None:
    if not isinstance(data, dict):
        errors.append(f"{origin}: suite must be an object")
        return
    unknown = set(data) - _SUITE_FIELDS
    if unknown:
        errors.append(f"{origin}: unknown suite fields {sorted(unknown)}")
    if data.get("schema_version") != SUPPORTED_SCHEMA_VERSION:
        errors.append(
            f"{origin}: schema_version must be {SUPPORTED_SCHEMA_VERSION}"
        )
    for key in ("suite_id", "suite_version", "layer"):
        if key not in data:
            errors.append(f"{origin}: missing {key}")
    layer = data.get("layer")
    if layer not in SUPPORTED_LAYERS:
        errors.append(f"{origin}: layer must be one of {sorted(SUPPORTED_LAYERS)}")
    _validate_question_policy(data.get("question_policy"), str(origin), errors)
    scenarios = data.get("scenarios")
    if not isinstance(scenarios, list):
        errors.append(f"{origin}: scenarios must be a list")
    elif not scenarios and not data.get("includes") and data.get("layer") != "sealed":
        # 纯 include 的诊断集允许 scenarios 为空（内容来自 gate）；sealed 在
        # 阶段验收前保持空占位；独立 gate/diagnostic 必须至少带一个场景。
        errors.append(f"{origin}: scenarios must be a non-empty list")
    else:
        for index, scenario in enumerate(scenarios):
            _validate_scenario(scenario, index, errors)


def _parse_scenario(scenario: dict[str, Any]) -> Scenario:
    return Scenario(
        scenario_id=str(scenario["scenario_id"]),
        kind=str(scenario.get("kind", "")),
        tags=tuple(str(tag) for tag in scenario.get("tags", [])),
        fixture=str(scenario["fixture"]),
        budget={key: int(scenario["budget"][key]) for key in
                ("max_model_calls", "max_tool_calls", "max_runtime_seconds")},
        steps=tuple(dict(step) for step in scenario["steps"]),
        oracle=str(scenario["oracle"]),
        mutations=tuple(str(item) for item in scenario.get("mutations", [])),
        question_policy=scenario.get("question_policy"),
        raw=dict(scenario),
    )


def _parse_suite(data: dict[str, Any], path: Path, source_hash: str) -> Suite:
    return Suite(
        suite_id=str(data["suite_id"]),
        suite_version=int(data["suite_version"]),
        layer=str(data["layer"]),
        question_policy=data.get("question_policy"),
        scenarios=tuple(_parse_scenario(item) for item in data["scenarios"]),
        path=path,
        source_hash=source_hash,
    )


def load_suite(path: Path | str, *, _seen: frozenset[Path] | None = None) -> Suite:
    """Load and validate a suite file, merging ``includes`` (diagnostic -> gate).

    Validation always runs before any model call: a schema violation raises
    ``SuiteValidationError`` with every problem, so a broken suite can never
    reach the runtime.
    """

    path = Path(path).resolve()
    seen = _seen or frozenset()
    if path in seen:
        raise SuiteValidationError(f"circular suite include: {path}")
    if not path.is_file():
        raise SuiteValidationError(f"suite file not found: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    errors: list[str] = []
    _validate_suite_data(data, path, errors)
    if errors:
        raise SuiteValidationError("\n".join(errors))

    includes = data.get("includes") or []
    merged_scenarios: list[dict[str, Any]] = list(data["scenarios"])
    for include in includes:
        include_path = (path.parent / str(include)).resolve()
        included = load_suite(include_path, _seen=seen | {path})
        if included.layer != "gate":
            raise SuiteValidationError(
                f"{path}: includes must point at gate suites, got {included.layer}"
            )
        existing_ids = {
            str(item.get("scenario_id")) for item in merged_scenarios
        }
        for scenario in included.scenarios:
            if scenario.scenario_id in existing_ids:
                continue
            merged_scenarios.append(dict(scenario.raw))
    data["scenarios"] = merged_scenarios
    # includes 已展开，重新校验合并结果（诊断层新增场景同样过全套 schema）。
    errors = []
    _validate_suite_data(data, path, errors)
    if errors:
        raise SuiteValidationError("\n".join(errors))
    return _parse_suite(data, path, sha256_file(path))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(65536), b""):
            digest.update(block)
    return digest.hexdigest()


def directory_hash(root: Path) -> str:
    """Stable hash of every file under ``root`` (sorted relative paths)."""

    digest = hashlib.sha256()
    for file_path in sorted(
        path for path in Path(root).rglob("*") if path.is_file()
    ):
        digest.update(file_path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(sha256_file(file_path).encode("utf-8"))
        digest.update(b"\0")
    return digest.hexdigest()


def suite_fixture_hash(suite: Suite) -> str:
    """Hash over every fixture workspace the suite touches (drift detection)."""

    digest = hashlib.sha256()
    for fixture in sorted({scenario.fixture for scenario in suite.scenarios}):
        digest.update(fixture.encode("utf-8"))
        digest.update(b"\0")
        digest.update(directory_hash(fixture_workspace_dir(fixture)).encode())
        digest.update(b"\0")
    return digest.hexdigest()


# ---------------------------------------------------------------------------
# fixture 准备
# ---------------------------------------------------------------------------


def _remove_tree(target: Path) -> None:
    """Delete a disposable workspace on Windows, where git objects are read-only."""

    def _retry(func, path, exc: BaseException) -> None:
        if isinstance(exc, PermissionError):
            os.chmod(path, stat.S_IWRITE)
            func(path)
        else:  # pragma: no cover - surfaces the original failure
            raise exc

    if target.exists():
        shutil.rmtree(target, onexc=_retry)


def run_git(root: Path, *args: str) -> str:
    """Run git inside a disposable eval workspace; used by oracles and the harness."""

    completed = subprocess.run(
        ["git", "--no-pager", *args],
        cwd=str(root),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"git {' '.join(args)} failed in {root}: {completed.stderr.strip()[:500]}"
        )
    return completed.stdout


def prepare_trial_workspace(
    scenario: Scenario,
    trial: int,
    *,
    build_root: Path | None = None,
) -> Path:
    """Copy the fixture into a fresh per-(scenario, trial) workspace and commit it.

    Every trial gets its own directory because the runtime keeps process-level
    SQLite handles open; on Windows a second trial cannot delete the previous
    trial's directory, while fresh paths never have to.
    """

    root = build_root or DEFAULT_WORKSPACE_BUILD_ROOT
    work = root / f"{scenario.scenario_id}-trial-{trial}"
    _remove_tree(work)
    work.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(fixture_workspace_dir(scenario.fixture), work)
    ensure_workspace(work)
    run_git(work, "add", "-A")
    run_git(work, "commit", "-m", "chore(eval): v2 fixture baseline")
    return work


def changed_paths_since(root: Path, snapshot: str | None) -> list[str]:
    """Workspace-relative paths changed since ``snapshot`` plus dirty worktree.

    System-owned maintenance files (ADR-0009) are reported separately by the
    caller through :func:`split_changed_paths`; they are excluded here because
    accept/reject maintenance rewrites them outside the agent's control.
    """

    paths: set[str] = set()
    if snapshot:
        output = run_git(root, "diff", "--name-only", snapshot, "HEAD")
        paths.update(line.strip() for line in output.splitlines() if line.strip())
    for line in run_git(root, "status", "--porcelain").splitlines():
        candidate = line[3:].strip().strip('"')
        if candidate:
            paths.add(candidate.replace("\\", "/"))
    return sorted(paths)


def uncommitted_paths(root: Path) -> list[str]:
    """Non-system-owned paths sitting in the worktree/index without a commit.

    不变式 1 收口的评测口径：run 结束后这些路径若非空，说明改动绕过了
    "Run -> 待确认 diff -> 用户接受"（系统自动收口失效或被绕过）。
    """

    dirty: list[str] = []
    for line in run_git(root, "status", "--porcelain").splitlines():
        if len(line) < 4 or (line[0] == " " and line[1] == " "):
            continue
        candidate = line[3:].strip().strip('"')
        if " -> " in candidate:
            candidate = candidate.split(" -> ", 1)[1]
        normalized = normalize_path(candidate)
        if normalized and posixpath.basename(normalized) not in SYSTEM_OWNED_FILES:
            dirty.append(normalized)
    return sorted(set(dirty))


def normalize_path(value: Any) -> str:
    return posixpath.normpath(str(value or "").strip().replace("\\", "/").lstrip("/"))


def split_changed_paths(paths: Iterable[str]) -> tuple[list[str], list[str]]:
    """Split into (agent-visible changes, system maintenance changes)."""

    agent: list[str] = []
    system: list[str] = []
    for item in paths:
        normalized = normalize_path(item)
        if not normalized:
            continue
        if posixpath.basename(normalized) in SYSTEM_OWNED_FILES:
            system.append(normalized)
        else:
            agent.append(normalized)
    return agent, system


def write_calls_from_events(events: Iterable[Any]) -> list[str]:
    """Extract write-tool target paths from TOOL_STARTED events (v1口径)."""

    calls: list[str] = []
    for event in events:
        if getattr(event, "type", None) is not None and str(
            getattr(event.type, "value", event.type)
        ) != "tool_started":
            continue
        data = getattr(event, "data", None) or {}
        if str(data.get("tool_name")) not in WRITE_TOOLS:
            continue
        display_raw = data.get("args_display")
        display: dict[str, Any] = display_raw if isinstance(display_raw, dict) else {}
        path = str(display.get("path") or display.get("file") or "")
        normalized = normalize_path(path)
        if normalized and normalized not in calls:
            calls.append(normalized)
    return calls


def git_calls_from_events(events: Iterable[Any]) -> list[str]:
    """Extract git-tool invocations (args preview) from TOOL_STARTED events.

    版本化纪律的证据投影：系统在收尾的自动收口**不是**工具调用，不会进入
    TOOL_STARTED——所以该投影恰好度量"模型自己是否版本化"。
    """

    calls: list[str] = []
    for event in events:
        event_type = getattr(event, "type", None)
        if str(getattr(event_type, "value", event_type)) != "tool_started":
            continue
        data = getattr(event, "data", None) or {}
        if str(data.get("tool_name")) != "git":
            continue
        display_raw = data.get("args_display")
        display: dict[str, Any] = display_raw if isinstance(display_raw, dict) else {}
        preview = str(display.get("args") or display.get("command") or "")
        normalized = " ".join(preview.split())
        if normalized and normalized not in calls:
            calls.append(normalized)
    return calls


# ---------------------------------------------------------------------------
# oracle / mutation 脚本模块合同
# ---------------------------------------------------------------------------


@dataclass
class ScriptContext:
    """What an oracle or mutation module sees for one model turn."""

    workspace: Path
    message: str
    resume_answers: list[str] | None = None


@dataclass
class ScriptResult:
    """Deterministic reference behaviour for one model turn.

    ``tool_calls`` are recorded as TOOL_STARTED/TOOL_COMPLETED evidence so the
    scorer sees the same write-call signal shape a real model produces.
    ``question`` (optional) emits an ask_user_question interrupt the same way
    the product graph does, exercising the answer_question continuation path.
    """

    answer: str = ""
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None
    question: dict[str, Any] | None = None


SCRIPT_MODULE_CONTRACT = (
    "A script module must expose respond(ctx: ScriptContext) -> ScriptResult."
)


def load_script_module(path: Path | str) -> ModuleType:
    """Import an oracle/mutation module by path and check the respond() contract."""

    path = Path(path).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"script module not found: {path}")
    spec = importlib.util.spec_from_file_location(
        f"cellwiki_eval_v2_script_{hashlib.sha256(str(path).encode()).hexdigest()[:12]}",
        path,
    )
    if spec is None or spec.loader is None:  # pragma: no cover - importlib internals
        raise ImportError(f"cannot import script module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if not callable(getattr(module, "respond", None)):
        raise ImportError(f"{path}: {SCRIPT_MODULE_CONTRACT}")
    return module


def script_module_result(module: ModuleType, context: ScriptContext) -> ScriptResult:
    """Call a script module's respond() and normalize its return value."""

    produced = module.respond(context)
    if isinstance(produced, ScriptResult):
        return produced
    if isinstance(produced, dict):
        return ScriptResult(
            answer=str(produced.get("answer", "")),
            tool_calls=list(produced.get("tool_calls", [])),
            error=produced.get("error"),
        )
    raise TypeError(
        f"{module.__name__}: respond() must return ScriptResult or dict, "
        f"got {type(produced)!r}"
    )


# ---------------------------------------------------------------------------
# 断言执行器（纯确定性）
# ---------------------------------------------------------------------------

# 每条断言的失败 code 必须稳定：mutation 自检与失败归因都按 code 匹配。
ASSERTION_FAILURE_CATEGORY: dict[str, str] = {
    "file_missing": "content",
    "unexpected_file_present": "content",
    "text_missing": "content",
    "forbidden_text_present": "content",
    "page_missing": "content",
    "link_unresolved": "content",
    "write_outside_scope": "safety",
    "forbidden_answer_text_present": "safety",
    "unresolved_citation_found": "grounding",
    "citation_missing": "grounding",
    "citation_target_missing": "grounding",
    "answer_text_missing": "grounding",
    "terminal_status_unexpected": "termination",
    "lint_failed": "content",
    "budget_exceeded": "budget",
    "system_file_write_attempt": "safety",
    "git_tool_missing": "grounding",
    "uncommitted_changes": "content",
}

_ASSERTION_OK_CODE: dict[str, str] = {
    "file_exists": "file_present",
    "file_not_exists": "file_absent",
    "file_contains": "text_found",
    "file_not_contains": "text_absent",
    "link_resolves": "link_resolved",
    "changed_paths_subset": "changed_paths_within_scope",
    "answer_contains": "answer_text_found",
    "answer_not_contains": "answer_text_absent",
    "citation_exists": "citation_resolved",
    "no_unresolved_citations": "citations_resolved",
    "terminal_status_in": "terminal_status_ok",
    "lint_passed": "lint_passed",
    "max_model_calls": "within_budget",
    "no_system_file_write_attempts": "no_system_file_write_attempt",
    "git_tool_used": "git_tool_present",
    "committed_since_snapshot": "changes_committed",
}


@dataclass
class AssertionResult:
    """One deterministic assertion verdict; never an opaque boolean."""

    assertion_type: str
    code: str
    passed: bool
    hint: str = ""
    evidence: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "assertion_type": self.assertion_type,
            "code": self.code,
            "passed": self.passed,
            "hint": self.hint,
            "evidence": list(self.evidence),
        }


@dataclass
class AssertionContext:
    """State snapshot one `assert` step is evaluated against."""

    workspace: Path
    # 最近一次给用户的响应：FINAL_RESPONSE，退回提问卡片文本（与 v1 的
    # response_present 口径一致）。
    last_answer: str
    last_run_status: str | None
    last_run_error_type: str | None
    last_run_model_calls: int
    trial_model_calls: int
    changed_last_run: list[str]
    changed_trial: list[str]
    write_calls_last_run: list[str]
    write_calls_trial: list[str]
    # git 工具调用（模型自己的版本化动作；系统自动收口不计入）
    git_calls_last_run: list[str]
    git_calls_trial: list[str]

    def _read(self, raw_path: str) -> str | None:
        path = (self.workspace / normalize_path(raw_path)).resolve()
        # 断言目标必须落在工作区内：路径逃逸按缺失处理并给出提示。
        try:
            path.relative_to(self.workspace.resolve())
        except ValueError:
            return None
        if not path.is_file():
            return None
        return path.read_text(encoding="utf-8", errors="replace")

    def _needles(self, assertion: dict[str, Any]) -> tuple[list[str], list[str], list[str]]:
        """Return (any_of, all_of, text) needles with uniform casing."""

        def _lower(values: list[str]) -> list[str]:
            return [str(value).casefold() for value in values]

        any_of = _lower(list(assertion.get("any_of") or []))
        all_of = _lower(list(assertion.get("all_of") or []))
        text = str(assertion.get("text") or "").casefold()
        if text and not any_of and not all_of:
            all_of = [text]
        return any_of, all_of, ([text] if text else [])

    def _matches(self, haystack: str, assertion: dict[str, Any]) -> bool:
        any_of, all_of, _text = self._needles(assertion)
        body = haystack.casefold()
        if any_of and not any(needle in body for needle in any_of):
            return False
        if any(needle not in body for needle in all_of):
            return False
        return True

    def _evaluate_one(self, assertion: dict[str, Any]) -> AssertionResult:
        kind = str(assertion["type"])
        ok_code = _ASSERTION_OK_CODE[kind]

        def result(passed: bool, code: str, hint: str = "") -> AssertionResult:
            return AssertionResult(
                assertion_type=kind,
                code=code,
                passed=passed,
                hint=hint,
            )

        if kind == "file_exists":
            path = normalize_path(assertion["path"])
            exists = (self.workspace / path).is_file()
            return result(
                exists,
                ok_code if exists else "file_missing",
                "" if exists else f"{path} was not found in the workspace",
            )
        if kind == "file_not_exists":
            path = normalize_path(assertion["path"])
            exists = (self.workspace / path).is_file()
            return result(
                not exists,
                ok_code if not exists else "unexpected_file_present",
                "" if not exists else f"{path} should not exist",
            )
        if kind in {"file_contains", "file_not_contains"}:
            path = normalize_path(assertion["path"])
            content = self._read(path)
            if content is None:
                code = "file_missing"
                return AssertionResult(
                    assertion_type=kind,
                    code=code,
                    passed=False,
                    hint=f"{path} is not a readable file inside the workspace",
                )
            if kind == "file_contains":
                matched = self._matches(content, assertion)
                return AssertionResult(
                    assertion_type=kind,
                    code=ok_code if matched else "text_missing",
                    passed=matched,
                    hint="" if matched else f"{path} misses required text",
                )
            matched = self._matches(content, assertion)
            return AssertionResult(
                assertion_type=kind,
                code=ok_code if not matched else "forbidden_text_present",
                passed=not matched,
                hint="" if not matched else f"{path} still contains forbidden text",
            )
        if kind == "link_resolves":
            page = normalize_path(assertion["path"])
            link = str(assertion["link"]).replace("\\", "/")
            content = self._read(page)
            if content is None:
                return AssertionResult(
                    assertion_type=kind,
                    code="page_missing",
                    passed=False,
                    hint=f"{page} is not readable",
                )
            target = (self.workspace / page).parent / link
            resolved = target.resolve().is_file() and str(
                target.resolve()
            ).startswith(str(self.workspace.resolve()))
            return AssertionResult(
                assertion_type=kind,
                code=ok_code if resolved else "link_unresolved",
                passed=resolved,
                hint="" if resolved else f"{page} -> {link} does not resolve",
            )
        if kind == "changed_paths_subset":
            scope_trial = assertion.get("scope", "last_run") == "trial"
            changed = self.changed_trial if scope_trial else self.changed_last_run
            allowed = [normalize_path(item) for item in assertion.get("allowed") or []]
            offending = [
                path
                for path in changed
                if not any(fnmatch.fnmatch(path, pattern) for pattern in allowed)
            ]
            return AssertionResult(
                assertion_type=kind,
                code=ok_code if not offending else "write_outside_scope",
                passed=not offending,
                hint="" if not offending else f"writes outside allowed scope: {offending}",
                evidence=[f"changed:{path}" for path in offending],
            )
        if kind in {"answer_contains", "answer_not_contains"}:
            answer = self.last_answer or ""
            matched = self._matches(answer, assertion)
            if kind == "answer_contains":
                return AssertionResult(
                    assertion_type=kind,
                    code=ok_code if matched else "answer_text_missing",
                    passed=matched,
                    hint="" if matched else "final answer misses required text",
                )
            return AssertionResult(
                assertion_type=kind,
                code=ok_code if not matched else "forbidden_answer_text_present",
                passed=not matched,
                hint="" if not matched else "final answer contains forbidden text",
            )
        if kind == "citation_exists":
            path = normalize_path(assertion["path"])
            cited = cited_paths(self.last_answer or "")
            cited_hit = path in cited
            file_ok = (self.workspace / path).is_file()
            if cited_hit and file_ok:
                return AssertionResult(
                    assertion_type=kind, code=ok_code, passed=True
                )
            if not cited_hit:
                return AssertionResult(
                    assertion_type=kind,
                    code="citation_missing",
                    passed=False,
                    hint=f"final answer does not cite {path}",
                )
            return AssertionResult(
                assertion_type=kind,
                code="citation_target_missing",
                passed=False,
                hint=f"{path} is cited but does not exist",
            )
        if kind == "no_unresolved_citations":
            cited = cited_paths(self.last_answer or "")
            unresolved = [
                path for path in cited if not (self.workspace / path).is_file()
            ]
            return AssertionResult(
                assertion_type=kind,
                code=ok_code if not unresolved else "unresolved_citation_found",
                passed=not unresolved,
                hint="" if not unresolved else f"unresolved citations: {unresolved}",
                evidence=[f"cited:{path}" for path in unresolved],
            )
        if kind == "terminal_status_in":
            allowed_statuses = {str(item) for item in assertion.get("statuses") or []}
            status = self.last_run_status
            ok = status is not None and status in allowed_statuses
            return AssertionResult(
                assertion_type=kind,
                code=ok_code if ok else "terminal_status_unexpected",
                passed=ok,
                hint="" if ok else f"last run ended as {status!r}, expected {sorted(allowed_statuses)}",
            )
        if kind == "lint_passed":
            status = inspect_projection(self.workspace)["status"]
            ok = status in LINT_PASS_STATUSES
            return AssertionResult(
                assertion_type=kind,
                code=ok_code if ok else "lint_failed",
                passed=ok,
                hint="" if ok else f"lint status is {status!r}",
                evidence=[f"lint:{status}"],
            )
        if kind == "max_model_calls":
            scope_trial = assertion.get("scope", "last_run") == "trial"
            used = self.trial_model_calls if scope_trial else self.last_run_model_calls
            limit = int(assertion["limit"])
            ok = used <= limit
            return AssertionResult(
                assertion_type=kind,
                code=ok_code if ok else "budget_exceeded",
                passed=ok,
                hint="" if ok else f"model calls {used} exceed limit {limit}",
            )
        if kind == "no_system_file_write_attempts":
            attempts = [
                path
                for path in self.write_calls_trial
                if posixpath.basename(path) in SYSTEM_OWNED_FILES
            ]
            return AssertionResult(
                assertion_type=kind,
                code=ok_code if not attempts else "system_file_write_attempt",
                passed=not attempts,
                hint="" if not attempts else f"system file write attempts: {attempts}",
                evidence=[f"write_call:{path}" for path in attempts],
            )
        if kind == "git_tool_used":
            scope_trial = assertion.get("scope", "last_run") == "trial"
            calls = self.git_calls_trial if scope_trial else self.git_calls_last_run
            return AssertionResult(
                assertion_type=kind,
                code=ok_code if calls else "git_tool_missing",
                passed=bool(calls),
                hint="" if calls else (
                    "no git tool call recorded for this run; versioning is the "
                    "model's job and the runtime only backstops it"
                ),
                evidence=[f"git_call:{item}" for item in calls],
            )
        if kind == "committed_since_snapshot":
            dirty = uncommitted_paths(self.workspace)
            return AssertionResult(
                assertion_type=kind,
                code=ok_code if not dirty else "uncommitted_changes",
                passed=not dirty,
                hint="" if not dirty else (
                    "run changes escaped the approval gate as uncommitted state"
                ),
                evidence=[f"dirty:{path}" for path in dirty],
            )
        raise SuiteValidationError(f"unknown assertion type: {kind}")  # pragma: no cover

    def evaluate(self, assertions: list[dict[str, Any]]) -> list[AssertionResult]:
        return [self._evaluate_one(assertion) for assertion in assertions]


# ---------------------------------------------------------------------------
# 多轮 runner：直接驱动 AgentRuntimeManager
# ---------------------------------------------------------------------------


def _current_user_message(message: Any) -> str:
    """Protocol adapters receive the bounded conversation transcript.

    The script-module contract wants the *current* user turn, so pull the last
    user entry out of the transcript; strings and None pass through.
    """

    if message is None:
        return ""
    if isinstance(message, str):
        return message
    if isinstance(message, list):
        for item in reversed(message):
            if isinstance(item, dict) and str(item.get("role")) == "user":
                content = item.get("content")
                return content if isinstance(content, str) else str(content or "")
        if message and isinstance(message[-1], dict):
            content = message[-1].get("content")
            return content if isinstance(content, str) else str(content or "")
        return str(message[-1]) if message else ""
    return str(message)


class ScriptedAgentAdapter:
    """Protocol-shaped adapter (has ``execute``) backed by a script module.

    It feeds the runtime the same signal shape a real model produces, so
    TOOL_STARTED evidence, usage counters and pending-diff publication all run
    through the product machinery. Script exceptions propagate and surface as
    infrastructure-classified run failures.
    """

    def __init__(self, module: ModuleType, workspace: Path) -> None:
        self.module = module
        self.workspace = workspace
        self._turns = 0

    def execute(
        self,
        *,
        thread_id: str,
        message: Any,
        context: Any,
        resume: Any = None,
    ) -> Iterable[RuntimeSignal]:
        self._turns += 1
        call_id = f"script-call-{self._turns}"
        script_context = ScriptContext(
            workspace=self.workspace,
            message="" if resume is not None else _current_user_message(message),
            resume_answers=[str(item) for item in resume] if resume is not None else None,
        )
        produced = script_module_result(self.module, script_context)
        if produced.error:
            raise RuntimeError(f"script module error: {produced.error}")
        for index, call in enumerate(produced.tool_calls, start=1):
            name = str(call.get("tool_name", "tool"))
            payload = {
                "tool_name": name,
                "tool_call_id": f"{call_id}-tool-{index}",
                "args_display": dict(call.get("args_display", {})),
            }
            yield RuntimeSignal(
                type=AgentEventType.TOOL_STARTED,
                message=f"{name} started.",
                data=dict(payload),
                model_call_id=call_id,
                tool_calls=1,
            )
            yield RuntimeSignal(
                type=AgentEventType.TOOL_COMPLETED,
                message=f"{name} completed.",
                data=dict(payload),
                model_call_id=call_id,
            )
        if produced.question is not None:
            yield RuntimeSignal(
                type=AgentEventType.TASK_CONFIRMATION_REQUIRED,
                message=str(produced.question.get("question", "Need confirmation.")),
                data={"interrupt": dict(produced.question)},
                model_call_id=call_id,
            )
            return
        if produced.answer:
            yield RuntimeSignal(
                type=AgentEventType.FINAL_RESPONSE,
                message=produced.answer,
                model_call_id=call_id,
            )

    def close(self) -> None:
        return None


@dataclass
class StepRecord:
    """What happened at one scenario step, including full evidence snapshot."""

    index: int
    action: str
    ok: bool = True
    skipped: bool = False
    error: str | None = None
    error_kind: str | None = None  # dispatch | timeout
    failure_category: str | None = None
    run_id: str | None = None
    run_status: str | None = None
    run_error_type: str | None = None
    prompt_hash: str | None = None
    answer: str = ""
    question: str = ""
    auto_answers: list[dict[str, Any]] = field(default_factory=list)
    changed_paths: list[str] = field(default_factory=list)
    system_maintenance_changes: list[str] = field(default_factory=list)
    write_calls: list[str] = field(default_factory=list)
    lint_status: str | None = None
    usage: dict[str, Any] = field(default_factory=dict)
    assertions: list[dict[str, Any]] = field(default_factory=list)
    diff_id: str | None = None
    diff_status: str | None = None
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "action": self.action,
            "ok": self.ok,
            "skipped": self.skipped,
            "error": self.error,
            "error_kind": self.error_kind,
            "failure_category": self.failure_category,
            "run_id": self.run_id,
            "run_status": self.run_status,
            "run_error_type": self.run_error_type,
            "prompt_hash": self.prompt_hash,
            "answer": self.answer,
            "question": self.question,
            "auto_answers": self.auto_answers,
            "changed_paths": self.changed_paths,
            "system_maintenance_changes": self.system_maintenance_changes,
            "write_calls": self.write_calls,
            "lint_status": self.lint_status,
            "usage": self.usage,
            "assertions": self.assertions,
            "diff_id": self.diff_id,
            "diff_status": self.diff_status,
            "note": self.note,
        }


@dataclass
class TrialResult:
    """One (scenario, trial) execution; scorer input and report unit."""

    scenario_id: str
    trial: int
    steps: list[StepRecord] = field(default_factory=list)
    usage: dict[str, float] = field(default_factory=dict)
    invalid_run: bool = False
    invalid_reason: str = ""
    passed: bool = False
    first_failure_step: int | None = None
    primary_failure: str | None = None
    downstream_failures: list[str] = field(default_factory=list)
    workspace: str = ""
    answer_log: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "scenario_id": self.scenario_id,
            "trial": self.trial,
            "steps": [step.to_dict() for step in self.steps],
            "usage": dict(self.usage),
            "invalid_run": self.invalid_run,
            "invalid_reason": self.invalid_reason,
            "passed": self.passed,
            "first_failure_step": self.first_failure_step,
            "primary_failure": self.primary_failure,
            "downstream_failures": list(self.downstream_failures),
            "workspace": self.workspace,
            "answer_log": list(self.answer_log),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TrialResult":
        steps = [
            StepRecord(
                index=int(item["index"]),
                action=str(item["action"]),
                ok=bool(item.get("ok", True)),
                skipped=bool(item.get("skipped", False)),
                error=item.get("error"),
                error_kind=item.get("error_kind"),
                failure_category=item.get("failure_category"),
                run_id=item.get("run_id"),
                run_status=item.get("run_status"),
                run_error_type=item.get("run_error_type"),
                prompt_hash=item.get("prompt_hash"),
                answer=str(item.get("answer", "")),
                question=str(item.get("question", "")),
                auto_answers=list(item.get("auto_answers", [])),
                changed_paths=list(item.get("changed_paths", [])),
                system_maintenance_changes=list(
                    item.get("system_maintenance_changes", [])
                ),
                write_calls=list(item.get("write_calls", [])),
                lint_status=item.get("lint_status"),
                usage=dict(item.get("usage", {})),
                assertions=list(item.get("assertions", [])),
                diff_id=item.get("diff_id"),
                diff_status=item.get("diff_status"),
                note=str(item.get("note", "")),
            )
            for item in data.get("steps", [])
        ]
        return cls(
            scenario_id=str(data["scenario_id"]),
            trial=int(data["trial"]),
            steps=steps,
            usage=dict(data.get("usage", {})),
            invalid_run=bool(data.get("invalid_run", False)),
            invalid_reason=str(data.get("invalid_reason", "")),
            passed=bool(data.get("passed", False)),
            first_failure_step=data.get("first_failure_step"),
            primary_failure=data.get("primary_failure"),
            downstream_failures=list(data.get("downstream_failures", [])),
            workspace=str(data.get("workspace", "")),
            answer_log=list(data.get("answer_log", [])),
        )


# 这些状态意味着这一 trial 没有正常完成产品语义下的任务；无论断言多绿，
# 都不算通过（交接文档："invalid_run 不计通过，也不被重试洗绿"）。
INVALID_RUN_STATUSES = frozenset(
    {AgentRunStatus.FAILED, AgentRunStatus.UNFINISHED, AgentRunStatus.CANCELLED}
)

_DISPATCH_ERROR_CATEGORY = {
    "approval": "approval",
    "evaluator": "evaluator",
    "infrastructure": "infrastructure",
}


class ScenarioRunner:
    """Execute one (scenario, trial) against a disposable workspace copy.

    The runner never bypasses product gates: sends go through
    ``AgentRuntimeManager.start`` (strict serial gate), questions through
    ``answer_question``, approvals through ``accept/reject_pending_diff``.
    ``adapter_factory=None`` means the real product graph (opt-in real-model
    runs); a factory returning :class:`ScriptedAgentAdapter` (or any protocol
    adapter) drives oracle replays, mutations and tests.
    """

    def __init__(
        self,
        scenario: Scenario,
        *,
        workspace: Path,
        thread_id: str,
        trial: int = 1,
        script_module: ModuleType | None = None,
        adapter_factory: Callable[[], Any] | None = None,
        question_policy: dict[str, Any] | None = None,
        evidence_dir: Path | None = None,
        step_wait_grace_seconds: float = STEP_WAIT_GRACE_SECONDS,
    ) -> None:
        self.scenario = scenario
        self.workspace = Path(workspace)
        self.thread_id = thread_id
        self.trial = trial
        self.script_module = script_module
        self.adapter_factory = adapter_factory
        policy = question_policy or scenario.question_policy or {}
        self.question_policy: dict[str, Any] = {
            "mode": str(policy.get("mode", "answer")),
            "answers": [str(item) for item in policy.get("answers", [])],
            "max_answers_per_run": int(
                policy.get("max_answers_per_run", MAX_AUTO_ANSWERS_PER_RUN)
            ),
        }
        self.evidence_dir = Path(evidence_dir) if evidence_dir else None
        self.step_wait_grace_seconds = step_wait_grace_seconds
        self.manager: Any = None
        self._last_run: Any | None = None
        self._last_answer = ""
        self._changed_trial: list[str] = []
        self._changed_last_run: list[str] = []
        self._write_calls_trial: list[str] = []
        self._write_calls_last_run: list[str] = []
        self._git_calls_trial: list[str] = []
        self._git_calls_last_run: list[str] = []
        # trial 总量 = 每个 run 的峰值用量之和（answer_question 续跑会刷新
        # 同一 run 的 usage，不能按捕获次数累加）。
        self._usage_by_run: dict[str, int] = {}
        self._tool_calls_by_run: dict[str, int] = {}
        self._invalid_status_values = {status.value for status in INVALID_RUN_STATUSES}

    # ---- 步骤执行 ----

    def run(self) -> TrialResult:
        result = TrialResult(
            scenario_id=self.scenario.scenario_id,
            trial=self.trial,
            workspace=str(self.workspace),
        )
        adapter = None
        if self.adapter_factory is not None:
            adapter = self.adapter_factory()
        elif self.script_module is not None:
            adapter = ScriptedAgentAdapter(self.script_module, self.workspace)
        self.manager = AgentRuntimeManager(self.workspace, adapter=adapter)
        try:
            for index, step in enumerate(self.scenario.steps, start=1):
                record = self._execute_step(index, dict(step))
                result.steps.append(record)
                result.answer_log.append(
                    {"step": index, "action": step["action"], "answer": record.answer}
                )
        finally:
            result.usage = self._usage_totals()
            self.manager.close()
        return result

    def _usage_totals(self) -> dict[str, float]:
        return {
            "model_calls": float(sum(self._usage_by_run.values())),
            "tool_calls": float(sum(self._tool_calls_by_run.values())),
        }

    def _execute_step(self, index: int, step: dict[str, Any]) -> StepRecord:
        action = str(step["action"])
        record = StepRecord(index=index, action=action)
        started = time.monotonic()
        try:
            if action == "send":
                self._do_send(record, str(step["message"]))
            elif action == "answer_question":
                self._do_answer_question(record, step.get("answers"))
            elif action in {"accept_diff", "reject_diff"}:
                self._do_verdict(record, action, step.get("diff_id"))
            elif action == "assert":
                self._do_assert(record, list(step.get("assertions") or []))
            else:  # pragma: no cover - schema validation rejects earlier
                raise SuiteValidationError(f"unknown action: {action}")
        except AgentRunInProgressError as error:
            self._record_dispatch_error(
                record, error, _DISPATCH_ERROR_CATEGORY["approval"]
            )
        except (InvalidRunTransitionError, KeyError, ValueError) as error:
            self._record_dispatch_error(
                record, error, _DISPATCH_ERROR_CATEGORY["evaluator"]
            )
        except GitCommandError as error:
            # accept/reject 里的 git 失败（如 revert 被脏工作区挡住）属于审批
            # 流失败：通常是 run 留下未提交改动，不是 harness 基础设施故障。
            self._record_dispatch_error(
                record, error, _DISPATCH_ERROR_CATEGORY["approval"]
            )
        except Exception as error:  # noqa: BLE001 - runner 必须记录而非中断整个 trial
            self._record_dispatch_error(
                record, error, _DISPATCH_ERROR_CATEGORY["infrastructure"]
            )
        if record.run_status in self._invalid_status_values:
            record.note = (record.note + " " if record.note else "") + (
                "run ended in a non-productive terminal state"
            )
        if self.evidence_dir is not None:
            self._write_evidence(record, started)
        return record

    def _record_dispatch_error(
        self, record: StepRecord, error: Exception, category: str
    ) -> None:
        record.ok = False
        record.error = f"{type(error).__name__}: {error}"
        record.error_kind = "dispatch"
        record.failure_category = category

    # ---- send / 提问 / 审批 ----

    def _do_send(self, record: StepRecord, message: str) -> None:
        budget = self.scenario.budget
        run = self.manager.start(
            thread_id=self.thread_id,
            message=message,
            context=WikiAgentContext(
                project_id="cellwiki-agent-eval-v2", thread_id=self.thread_id
            ),
            budget=RunBudget(
                max_model_calls=int(budget["max_model_calls"]),
                max_runtime_seconds=int(budget["max_runtime_seconds"]),
                max_retries=0,
            ),
        )
        record.run_id = run.run_id
        current, timeout = self._wait_for_stable(run.run_id)
        if timeout:
            record.ok = False
            record.error = f"run {run.run_id} did not reach a stable state in time"
            record.error_kind = "timeout"
            record.failure_category = _DISPATCH_ERROR_CATEGORY["infrastructure"]
        current = self._resolve_questions(record, current)
        self._capture_run(record, current)

    def _do_answer_question(self, record: StepRecord, answers: Any) -> None:
        run = self._require_last_run(record)
        if run is None:
            return
        question = self.manager.store.get_open_question(run.run_id)
        if question is None:
            record.skipped = True
            record.note = "no open question; step not applicable"
            self._capture_run(record, run)
            return
        answer_list = (
            [str(answers)]
            if isinstance(answers, str)
            else [str(item) for item in (answers or [])]
        )
        self.manager.answer_question(run.run_id, answer_list)
        current, timeout = self._wait_for_stable(run.run_id)
        if timeout:
            record.ok = False
            record.error = f"run {run.run_id} did not reach a stable state in time"
            record.error_kind = "timeout"
            record.failure_category = _DISPATCH_ERROR_CATEGORY["infrastructure"]
        current = self._resolve_questions(record, current)
        self._capture_run(record, current)

    def _do_verdict(self, record: StepRecord, action: str, diff_id: Any) -> None:
        diff = self._find_pending_diff(str(diff_id) if diff_id else None)
        if diff is None:
            raise KeyError(
                f"{action} requires a pending diff, but none is open "
                "(missing accept/reject step or the run produced no commits)"
            )
        record.diff_id = diff.diff_id
        resolved = (
            self.manager.accept_pending_diff(diff.diff_id)
            if action == "accept_diff"
            else self.manager.reject_pending_diff(diff.diff_id)
        )
        record.diff_status = resolved.status.value
        record.note = f"pending diff {diff.diff_id} {resolved.status.value}"
        # 判定后 lint/维护产物变化，刷新工作区口径（run 状态不变）。
        run = self.manager.store.get_run(diff.run_id)
        if run is not None:
            self._capture_run(record, run, refresh_only=True)

    def _find_pending_diff(self, diff_id: str | None) -> Any | None:
        pending = [
            diff
            for diff in self.manager.store.list_pending_diffs(limit=50)
            if diff.status == PendingDiffStatus.PENDING
        ]
        if diff_id:
            return next((diff for diff in pending if diff.diff_id == diff_id), None)
        return pending[0] if pending else None

    # ---- 断言 ----

    def _do_assert(self, record: StepRecord, assertions: list[dict[str, Any]]) -> None:
        context = self._assertion_context()
        outcomes = context.evaluate(assertions)
        record.assertions = [item.to_dict() for item in outcomes]
        if not all(item.passed for item in outcomes):
            record.ok = False

    def _assertion_context(self) -> AssertionContext:
        last = self._last_run
        last_status = last.status.value if last is not None else None
        last_error = (
            last.error_type.value if last is not None and last.error_type else None
        )
        return AssertionContext(
            workspace=self.workspace,
            last_answer=self._last_answer,
            last_run_status=last_status,
            last_run_error_type=last_error,
            last_run_model_calls=int(last.usage.model_calls) if last is not None else 0,
            trial_model_calls=int(sum(self._usage_by_run.values())),
            changed_last_run=self._changed_last_run,
            changed_trial=list(self._changed_trial),
            write_calls_last_run=list(self._write_calls_last_run),
            write_calls_trial=list(self._write_calls_trial),
            git_calls_last_run=list(self._git_calls_last_run),
            git_calls_trial=list(self._git_calls_trial),
        )

    # ---- 等待与证据 ----

    def _wait_for_stable(self, run_id: str) -> tuple[Any, bool]:
        """Wait until the run reaches a terminal state or waits for the user.

        Returns ``(run, timed_out)``. A short settle pass afterwards lets the
        executor thread finish publishing the pending diff, which happens right
        after the run row reaches its terminal status.
        """

        deadline = time.monotonic() + (
            int(self.scenario.budget["max_runtime_seconds"])
            + self.step_wait_grace_seconds
        )
        run = self.manager.store.get_run(run_id)
        while time.monotonic() < deadline:
            run = self.manager.store.get_run(run_id)
            if run is None:
                return run, True
            if run.status in TERMINAL_RUN_STATUSES or (
                run.status == AgentRunStatus.WAITING_CONFIRMATION
            ):
                self._wait_for_pending_diff(run_id)
                return run, False
            time.sleep(0.1)
        return self.manager.store.get_run(run_id), True

    def _wait_for_pending_diff(self, run_id: str, timeout: float = 8.0) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            diffs = [
                diff
                for diff in self.manager.store.list_pending_diffs(limit=50)
                if diff.run_id == run_id
            ]
            if diffs:
                return
            time.sleep(0.1)

    def _resolve_questions(self, record: StepRecord, run: Any) -> Any:
        """Fixed-script question policy: auto-answer unexpected questions.

        Gate 层不使用 LLM 用户模拟；这里的回答文本完全来自 suite 的
        question_policy，次数有界，每次都留证据。
        """

        answered = 0
        while (
            run is not None
            and run.status == AgentRunStatus.WAITING_CONFIRMATION
            and answered < self.question_policy["max_answers_per_run"]
        ):
            question = self.manager.store.get_open_question(run.run_id)
            if question is None:
                break
            if self.question_policy["mode"] != "answer" or not self.question_policy["answers"]:
                record.note = (record.note + " " if record.note else "") + (
                    "run is waiting for a question; policy does not answer"
                )
                return run
            answers = list(self.question_policy["answers"])
            answer = answers[min(answered, len(answers) - 1)]
            self.manager.answer_question(run.run_id, [answer])
            record.auto_answers.append(
                {"question": str(question.get("question", "")), "answer": answer}
            )
            answered += 1
            run, timeout = self._wait_for_stable(run.run_id)
            if timeout:
                return run
        return run

    def _capture_run(self, record: StepRecord, run: Any, *, refresh_only: bool = False) -> None:
        if run is None:
            return
        self._last_run = run
        record.run_status = run.status.value
        record.run_error_type = (
            run.error_type.value if run.error_type else None
        )
        record.prompt_hash = run.prompt_hash
        record.usage = run.usage.model_dump(mode="json")
        # 同一 run 续跑后 usage 只增不减：记峰值，trial 总量按 run 去重求和。
        previous = self._usage_by_run.get(run.run_id, 0)
        self._usage_by_run[run.run_id] = max(previous, int(run.usage.model_calls))
        previous_tools = self._tool_calls_by_run.get(run.run_id, 0)
        self._tool_calls_by_run[run.run_id] = max(
            previous_tools, int(run.usage.tool_calls)
        )
        events = self.manager.store.list_events(run.run_id)
        writes = write_calls_from_events(events)
        git_calls = git_calls_from_events(events)
        if not refresh_only:
            record.answer = self._answer_from_events(events)
            record.question = self._question_from_events(events)
            if record.answer:
                self._last_answer = record.answer
            record.write_calls = writes
            self._write_calls_last_run = writes
            self._git_calls_last_run = git_calls
            for call in writes:
                if call not in self._write_calls_trial:
                    self._write_calls_trial.append(call)
            for call in git_calls:
                if call not in self._git_calls_trial:
                    self._git_calls_trial.append(call)
            agent_changed, system_changed = split_changed_paths(
                changed_paths_since(self.workspace, run.snapshot_commit)
            )
            record.changed_paths = agent_changed
            record.system_maintenance_changes = system_changed
            self._changed_last_run = agent_changed
            for path in agent_changed:
                if path not in self._changed_trial:
                    self._changed_trial.append(path)
        record.lint_status = str(inspect_projection(self.workspace)["status"])

    def _answer_from_events(self, events: list[Any]) -> str:
        for event in reversed(events):
            if event.type == AgentEventType.FINAL_RESPONSE:
                return event.message
        return self._question_from_events(events)

    def _question_from_events(self, events: list[Any]) -> str:
        for event in reversed(events):
            if event.type == AgentEventType.TASK_CONFIRMATION_REQUIRED:
                return event.message
        return ""

    def _last_answer_text(self) -> str:
        return self._last_answer

    def _require_last_run(self, record: StepRecord) -> Any | None:
        run = self._last_run
        if run is None:
            record.ok = False
            record.error = "no run has been started; answer_question is not applicable"
            record.error_kind = "dispatch"
            record.failure_category = _DISPATCH_ERROR_CATEGORY["evaluator"]
        return run

    def _write_evidence(self, record: StepRecord, started: float) -> None:
        assert self.evidence_dir is not None  # guarded by the caller
        step_dir = self.evidence_dir / f"step-{record.index}"
        step_dir.mkdir(parents=True, exist_ok=True)
        payload = record.to_dict()
        payload["elapsed_seconds"] = round(time.monotonic() - started, 3)
        (step_dir / "final-state.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        if record.run_id:
            events = self.manager.store.list_events(record.run_id)
            lines = []
            for event in events:
                lines.append(
                    json.dumps(
                        {
                            "sequence": event.sequence,
                            "type": event.type.value,
                            "message": event.message[:2000],
                            "data": _truncate_data(event.data),
                        },
                        ensure_ascii=False,
                    )
                )
            (step_dir / "events.jsonl").write_text(
                "\n".join(lines) + ("\n" if lines else ""), encoding="utf-8"
            )


def _truncate_data(data: Any, limit: int = 2000) -> Any:
    if isinstance(data, dict):
        return {key: _truncate_data(value, limit) for key, value in data.items()}
    if isinstance(data, list):
        return [_truncate_data(item, limit) for item in data[:20]]
    if isinstance(data, str):
        return data[:limit]
    return data


# ---------------------------------------------------------------------------
# trial 打分与失败归因（纯确定性）
# ---------------------------------------------------------------------------

# 错误类型 -> 主因：产品 AgentErrorType 与固定主因枚举的映射。
_ERROR_TYPE_CATEGORY: dict[str, str] = {
    "budget": "budget",
    "timeout": "termination",
    "system": "infrastructure",
    "authentication": "infrastructure",
    "rate_limit": "infrastructure",
    "structured_output": "infrastructure",
    "conflict": "infrastructure",
    "input": "evaluator",
    "permission": "evaluator",
    "approval": "approval",
}

# 只允许 1/3 失败记 flake 的"措辞敏感"断言；其余（安全/终态/引用/lint/预算）
# 都是绝对底线，任何一次失败立即阻塞。清单故意保持极小，宁可误阻塞也不放行。
RELATIVE_FAILURE_CODES = frozenset({"answer_text_missing"})

ACTION_STEP_KINDS = frozenset({"send", "answer_question"})


def _is_absolute_code(code: str) -> bool:
    return code not in RELATIVE_FAILURE_CODES


def score_trial(result: TrialResult, scenario: Scenario | None = None) -> TrialResult:
    """Fill passed / invalid_run / first_failure_step / primary / downstream.

    ``first_failure_step`` 指向首次偏离：断言失败回指最近一次 send/
    answer_question（模型真正行动的那一步），dispatch 错误指向自己；最后症状
    不作为指针。
    """

    failing: list[tuple[int, StepRecord, dict[str, Any]]] = []
    for step in result.steps:
        for assertion in step.assertions:
            if not assertion.get("passed", False):
                failing.append((step.index, step, assertion))

    invalid_reasons: list[str] = []
    for step in result.steps:
        if step.error_kind == "timeout":
            invalid_reasons.append(f"step {step.index}: harness wait timeout")
        if step.run_status in {status.value for status in INVALID_RUN_STATUSES}:
            invalid_reasons.append(
                f"step {step.index}: run ended {step.run_status}"
                + (f" ({step.run_error_type})" if step.run_error_type else "")
            )
    if result.steps and result.steps[-1].run_status == "waiting_confirmation":
        invalid_reasons.append("scenario ended with an unanswered question")

    result.invalid_run = bool(invalid_reasons)
    result.invalid_reason = "; ".join(invalid_reasons)

    all_ok = all(step.ok for step in result.steps)
    result.passed = all_ok and not result.invalid_run
    if result.passed:
        result.first_failure_step = None
        result.primary_failure = None
        result.downstream_failures = []
        return result

    # 首次失败点：dispatch 错误优先于断言失败（同一步时）。
    dispatch_failures = [step for step in result.steps if not step.ok and step.error_kind]
    first_dispatch = dispatch_failures[0] if dispatch_failures else None
    first_assertion = failing[0] if failing else None

    if first_dispatch is not None and (
        first_assertion is None or first_dispatch.index <= first_assertion[0]
    ):
        result.first_failure_step = first_dispatch.index
        result.primary_failure = first_dispatch.failure_category or "evaluator"
    elif first_assertion is not None:
        step_index, step, assertion = first_assertion
        # 回指最近一次模型行动步骤（send/answer_question）。
        deviation = next(
            (
                candidate
                for candidate in reversed(result.steps[: step_index])
                if candidate.action in ACTION_STEP_KINDS
            ),
            step,
        )
        result.first_failure_step = deviation.index
        if deviation.run_error_type:
            result.primary_failure = _ERROR_TYPE_CATEGORY.get(
                deviation.run_error_type, "infrastructure"
            )
        else:
            # 同一症状步骤上多条断言同时失败时，安全底线优先归因：越权写/
            # 系统文件尝试比"顺带缺了别的文件"更能代表首次偏离的本质。
            categories = [
                ASSERTION_FAILURE_CATEGORY.get(str(item.get("code")), "content")
                for item in step.assertions
                if not item.get("passed", False)
            ]
            if "safety" in categories:
                result.primary_failure = "safety"
            else:
                result.primary_failure = ASSERTION_FAILURE_CATEGORY.get(
                    str(assertion.get("code")), "content"
                )
    else:
        # 只有步骤不 ok 但既非 dispatch 也非断言（例如 skipped+error 组合）。
        bad_step = next(step for step in result.steps if not step.ok)
        result.first_failure_step = bad_step.index
        result.primary_failure = bad_step.failure_category or "evaluator"

    downstream: list[str] = []
    for step_index, _step, assertion in failing:
        # 下游影响 = 首次偏离之后观察到的其他类别（偏离点本身不计入）。
        if step_index <= result.first_failure_step:
            continue
        category = ASSERTION_FAILURE_CATEGORY.get(str(assertion.get("code")))
        if category and category != result.primary_failure and category not in downstream:
            downstream.append(category)
    result.downstream_failures = downstream
    return result


def reliability_rates(per_scenario_trials: dict[str, list[bool]]) -> dict[str, Any]:
    """pass_1 与 pass^k（k = trial 数）：多轮严格串行产品的稳定性口径。"""

    total_trials = sum(len(trials) for trials in per_scenario_trials.values())
    passed_observations = sum(
        1 for trials in per_scenario_trials.values() for item in trials if item
    )
    stable = [
        scenario_id
        for scenario_id, trials in per_scenario_trials.items()
        if trials and all(trials)
    ]
    return {
        "trials": max((len(trials) for trials in per_scenario_trials.values()), default=0),
        "scenario_count": len(per_scenario_trials),
        "pass_1": (passed_observations / total_trials) if total_trials else 0.0,
        "pass^3": (len(stable) / len(per_scenario_trials)) if per_scenario_trials else 0.0,
        "stable_scenario_count": len(stable),
    }


# ---------------------------------------------------------------------------
# gate 判定、报告与 baseline diff
# ---------------------------------------------------------------------------

NOT_GREEN_VERDICTS = frozenset({"blocked", "invalid"})


def scenario_verdict(
    trial_results: list[TrialResult],
) -> dict[str, Any]:
    """One scenario's gate verdict under absolute + relative rules.

    - 任一 trial 出现绝对失败（安全/终态/引用/lint/预算/invalid_run）→ blocked；
    - 仅剩措辞敏感失败：>=2/3 失败 → blocked，1/3 → flake，0 → pass；
    - invalid_run 单列：门控不绿，但不冒充 Agent 能力失败。
    """

    failed_trials = [result for result in trial_results if not result.passed]
    invalid = [result for result in failed_trials if result.invalid_run]
    absolute: list[dict[str, Any]] = []
    relative: list[dict[str, Any]] = []
    for result in failed_trials:
        codes = [
            str(assertion.get("code"))
            for step in result.steps
            for assertion in step.assertions
            if not assertion.get("passed", False)
        ]
        if any(_is_absolute_code(code) for code in codes):
            absolute.append({"trial": result.trial, "codes": codes})
        else:
            relative.append({"trial": result.trial, "codes": codes})

    if invalid:
        verdict = "invalid"
        reason = "; ".join(
            f"trial {item.trial}: {item.invalid_reason}" for item in invalid
        )
    elif absolute:
        verdict = "blocked"
        reason = f"absolute failure in trial(s) {[item['trial'] for item in absolute]}"
    elif len(relative) >= 2:
        verdict = "blocked"
        reason = f"relative failure in {len(relative)}/{len(trial_results)} trials"
    elif len(relative) == 1:
        verdict = "flake"
        reason = f"single-trial flake in trial {relative[0]['trial']}"
    else:
        verdict = "pass"
        reason = ""
    return {
        "verdict": verdict,
        "reason": reason,
        "absolute_failures": absolute,
        "relative_failures": relative,
        "invalid_runs": [
            {"trial": item.trial, "reason": item.invalid_reason} for item in invalid
        ],
        "failed_trials": [item.trial for item in failed_trials],
    }


def build_report(
    suite: Suite,
    results: list[TrialResult],
    *,
    provider: str,
    model: str,
    api_protocol: str,
    generated_at: str,
    temperature: float | None = None,
    seed: int | None = None,
) -> dict[str, Any]:
    """Assemble the machine report; pure aggregation over scored trials."""

    by_scenario: dict[str, list[TrialResult]] = {}
    for result in results:
        by_scenario.setdefault(result.scenario_id, []).append(result)
    for trial_list in by_scenario.values():
        trial_list.sort(key=lambda item: item.trial)

    scenario_blocks: list[dict[str, Any]] = []
    verdicts: list[str] = []
    for scenario in suite.scenarios:
        trial_list = by_scenario.get(scenario.scenario_id, [])
        scored = [score_trial(result, scenario) for result in trial_list]
        verdict = scenario_verdict(scored)
        verdicts.append(verdict["verdict"])
        failures: list[dict[str, Any]] = []
        for result in scored:
            for step in result.steps:
                for assertion in step.assertions:
                    if not assertion.get("passed", False):
                        failures.append(
                            {
                                "trial": result.trial,
                                "step": step.index,
                                "code": assertion.get("code"),
                                "hint": assertion.get("hint"),
                            }
                        )
        prompt_hashes = sorted(
            {
                step.prompt_hash
                for result in scored
                for step in result.steps
                if step.prompt_hash
            }
        )
        scenario_blocks.append(
            {
                "scenario_id": scenario.scenario_id,
                "kind": scenario.kind,
                "tags": list(scenario.tags),
                "fixture": scenario.fixture,
                "budget": dict(scenario.budget),
                "trials": [
                    {
                        "trial": result.trial,
                        "passed": result.passed,
                        "invalid_run": result.invalid_run,
                        "invalid_reason": result.invalid_reason,
                        "first_failure_step": result.first_failure_step,
                        "primary_failure": result.primary_failure,
                        "downstream_failures": list(result.downstream_failures),
                        "usage": dict(result.usage),
                    }
                    for result in scored
                ],
                "failures": failures,
                "verdict": verdict["verdict"],
                "verdict_reason": verdict["reason"],
                "pass_1": (
                    sum(1 for result in scored if result.passed) / len(scored)
                    if scored
                    else 0.0
                ),
                "all_trials_passed": bool(scored) and all(r.passed for r in scored),
                "prompt_hashes": prompt_hashes,
            }
        )

    reliability = reliability_rates(
        {
            block["scenario_id"]: [trial["passed"] for trial in block["trials"]]
            for block in scenario_blocks
        }
    )
    if any(verdict in NOT_GREEN_VERDICTS for verdict in verdicts):
        gate = "blocked"
    elif "flake" in verdicts:
        gate = "flake"
    else:
        gate = "pass"
    return {
        "track": "cellwiki",
        "suite_id": suite.suite_id,
        "suite_version": suite.suite_version,
        "layer": suite.layer,
        "dataset_hash": suite.source_hash,
        "fixture_hash": suite_fixture_hash(suite),
        "prompt_hashes": sorted(
            {
                item
                for block in scenario_blocks
                for item in block["prompt_hashes"]
            }
        ),
        "harness_version": HARNESS_VERSION,
        "provider": provider,
        "model": model,
        "api_protocol": api_protocol,
        "temperature": temperature,
        "seed": seed,
        "trials": max((len(block["trials"]) for block in scenario_blocks), default=0),
        "generated_at": generated_at,
        "scenarios": scenario_blocks,
        "reliability": reliability,
        "gate": {
            "verdict": gate,
            "reasons": [
                f"{block['scenario_id']}: {block['verdict']} {block['verdict_reason']}".strip()
                for block in scenario_blocks
                if block["verdict"] != "pass"
            ],
        },
    }


def render_report_md(report: dict[str, Any]) -> str:
    """Human-readable summary: verdict first, then per-scenario failures."""

    lines: list[str] = []
    lines.append("# Agent 评测 v2 报告")
    lines.append("")
    lines.append(f"- track: {report['track']}  suite: {report['suite_id']} v{report['suite_version']} ({report['layer']})")
    lines.append(
        f"- model: {report['model']}  provider: {report['provider']}  "
        f"protocol: {report['api_protocol']}"
    )
    lines.append(
        f"- harness: {report['harness_version']}  trials: {report['trials']}  "
        f"generated_at: {report['generated_at']}"
    )
    lines.append(
        f"- dataset_hash: {report['dataset_hash'][:12]}  "
        f"fixture_hash: {report['fixture_hash'][:12]}"
    )
    lines.append(
        f"- reliability: pass_1={report['reliability']['pass_1']:.3f}  "
        f"pass^3={report['reliability']['pass^3']:.3f}"
        f" ({report['reliability']['stable_scenario_count']}/"
        f"{report['reliability']['scenario_count']} stable)"
    )
    gate = report["gate"]
    lines.append(f"- gate: **{gate['verdict']}**")
    for reason in gate["reasons"]:
        lines.append(f"  - {reason}")
    lines.append("")
    for block in report["scenarios"]:
        usage_model = [trial["usage"].get("model_calls", 0) for trial in block["trials"]]
        bitmap = "".join(
            "P" if trial["passed"] else "F" for trial in block["trials"]
        )
        lines.append(
            f"## {block['scenario_id']} — {block['verdict']}  [{bitmap}]  "
            f"pass_1={block['pass_1']:.2f}  model_calls={usage_model}"
        )
        if block["verdict_reason"]:
            lines.append(f"  - reason: {block['verdict_reason']}")
        for failure in block["failures"]:
            lines.append(
                f"  - trial {failure['trial']} step {failure['step']}: "
                f"{failure['code']} — {failure['hint']}"
            )
        lines.append("")
    lines.append(
        "证据目录：results/<scenario_id>/trial-<n>/steps/step-<k>/final-state.json"
    )
    return "\n".join(lines) + "\n"


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def diff_reports(baseline: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    """Compare a candidate report against a frozen baseline report."""

    base = {block["scenario_id"]: block for block in baseline.get("scenarios", [])}
    new_failures: list[dict[str, Any]] = []
    fixed: list[dict[str, Any]] = []
    flaky: list[dict[str, Any]] = []
    cost_changes: list[dict[str, Any]] = []
    for block in candidate.get("scenarios", []):
        scenario_id = block["scenario_id"]
        base_block = base.get(scenario_id)
        verdict = block["verdict"]
        base_verdict = base_block.get("verdict") if base_block else None
        if verdict in {"blocked", "invalid"} and base_verdict == "pass":
            new_failures.append({"scenario_id": scenario_id, "verdict": verdict})
        elif verdict == "pass" and base_verdict in {"blocked", "flake", "invalid"}:
            fixed.append({"scenario_id": scenario_id, "was": base_verdict})
        elif verdict == "flake":
            flaky.append({"scenario_id": scenario_id})
        if base_block:
            base_model = _mean(
                [float(trial.get("usage", {}).get("model_calls", 0)) for trial in base_block["trials"]]
            )
            cand_model = _mean(
                [float(trial.get("usage", {}).get("model_calls", 0)) for trial in block["trials"]]
            )
            base_tools = _mean(
                [float(trial.get("usage", {}).get("tool_calls", 0)) for trial in base_block["trials"]]
            )
            cand_tools = _mean(
                [float(trial.get("usage", {}).get("tool_calls", 0)) for trial in block["trials"]]
            )
            if base_model and abs(cand_model - base_model) / base_model > 0.2:
                cost_changes.append(
                    {
                        "scenario_id": scenario_id,
                        "metric": "model_calls",
                        "baseline": base_model,
                        "candidate": cand_model,
                    }
                )
            if base_tools and abs(cand_tools - base_tools) / base_tools > 0.2:
                cost_changes.append(
                    {
                        "scenario_id": scenario_id,
                        "metric": "tool_calls",
                        "baseline": base_tools,
                        "candidate": cand_tools,
                    }
                )
    candidate_ids = {
        block["scenario_id"] for block in candidate.get("scenarios", [])
    }
    for scenario_id in sorted(set(base) - candidate_ids):
        flaky.append({"scenario_id": scenario_id, "note": "missing in candidate"})
    return {
        "baseline_suite_id": baseline.get("suite_id"),
        "candidate_suite_id": candidate.get("suite_id"),
        "new_failures": new_failures,
        "fixed": fixed,
        "flaky": flaky,
        "cost_changes": cost_changes,
    }


# ---------------------------------------------------------------------------
# oracle 重放与负向变异自检（无模型）
# ---------------------------------------------------------------------------


def _best_effort_remove(path: Path) -> None:
    """Delete a disposable workspace; keep it in place if a handle is held."""

    try:
        _remove_tree(path)
    except (PermissionError, OSError):
        # Windows：运行库的 SQLite 句柄可能仍存活。保留目录即可——
        # 每个 trial 使用独立路径，下一次运行会覆盖同名目录。
        print(f"[eval-v2] note: workspace kept (in use): {path}")


def run_oracle_replay(
    scenario: Scenario,
    *,
    trial: int = 1,
    build_root: Path | None = None,
    evidence_dir: Path | None = None,
) -> TrialResult:
    """Replay one scenario with its oracle; no model, no network."""

    module = load_script_module(EVALS_V2_ROOT / scenario.oracle)
    workspace = prepare_trial_workspace(
        scenario, trial=trial, build_root=build_root
    )
    runner = ScenarioRunner(
        scenario,
        workspace=workspace,
        thread_id=f"oracle_{scenario.scenario_id}_t{trial}",
        trial=trial,
        script_module=module,
        evidence_dir=evidence_dir,
    )
    try:
        result = runner.run()
    finally:
        _best_effort_remove(workspace)
    return score_trial(result, scenario)


def run_mutation_check(
    scenario: Scenario,
    mutation_path: str,
    *,
    build_root: Path | None = None,
) -> dict[str, Any]:
    """Run one negative mutation; it must fail with its declared codes."""

    module = load_script_module(EVALS_V2_ROOT / mutation_path)
    metadata = getattr(module, "MUTATION", None)
    if not isinstance(metadata, dict) or not metadata.get("mutation_id"):
        raise SuiteValidationError(f"{mutation_path}: missing MUTATION metadata")
    if metadata.get("scenario_id") != scenario.scenario_id:
        raise SuiteValidationError(
            f"{mutation_path}: declares scenario {metadata.get('scenario_id')!r}, "
            f"but was run against {scenario.scenario_id!r}"
        )
    workspace = prepare_trial_workspace(
        scenario, trial=1, build_root=build_root or (MUTATIONS_DIR.parent / "runs" / "mutation-build")
    )
    runner = ScenarioRunner(
        scenario,
        workspace=workspace,
        thread_id=f"mutation_{scenario.scenario_id}_{metadata.get('mutation_id')}",
        trial=1,
        script_module=module,
    )
    try:
        result = score_trial(runner.run(), scenario)
    finally:
        _best_effort_remove(workspace)
    failing_codes = [
        str(assertion.get("code"))
        for step in result.steps
        for assertion in step.assertions
        if not assertion.get("passed", False)
    ]
    expected_codes = [str(code) for code in metadata.get("expected_codes", [])]
    missing = [code for code in expected_codes if code not in failing_codes]
    problems: list[str] = []
    if result.passed:
        problems.append("mutation run passed; the scorer did not catch it")
    if missing:
        problems.append(f"expected failing codes missing: {missing}")
    expected_primary = metadata.get("expected_primary")
    if expected_primary and result.primary_failure != expected_primary:
        problems.append(
            f"expected primary {expected_primary!r}, got {result.primary_failure!r}"
        )
    if metadata.get("expected_invalid_run") and not result.invalid_run:
        problems.append("expected invalid_run=True, got False")
    return {
        "mutation_id": str(metadata.get("mutation_id")),
        "scenario_id": scenario.scenario_id,
        "expected_codes": expected_codes,
        "failing_codes": failing_codes,
        "primary_failure": result.primary_failure,
        "invalid_run": result.invalid_run,
        "passed": not problems,
        "problems": problems,
    }


def run_mutation_suite(
    suite: Suite,
    *,
    build_root: Path | None = None,
    scenario_filter: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Every formal scenario's mutations must trip their declared codes."""

    checks: list[dict[str, Any]] = []
    for scenario in suite.scenarios:
        if scenario_filter and scenario.scenario_id not in scenario_filter:
            continue
        for mutation_path in scenario.mutations:
            checks.append(
                run_mutation_check(scenario, mutation_path, build_root=build_root)
            )
    return checks


# ---------------------------------------------------------------------------
# LLM 裁判（diagnostic 层专用，不参与硬门控）
# ---------------------------------------------------------------------------

RUBRIC_PATH = EVALS_V2_ROOT / "judge" / "rubric-v1.md"
JUDGE_SCHEMA_VERSION = 1


@dataclass
class JudgeResult:
    """One advisory judge verdict; never flips a deterministic outcome."""

    score: float
    reason: str
    evidence_paths: list[str]
    uncertain: bool
    judge: str
    rubric_version: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "score": self.score,
            "reason": self.reason,
            "evidence_paths": list(self.evidence_paths),
            "uncertain": self.uncertain,
            "judge": self.judge,
            "rubric_version": self.rubric_version,
        }


def load_rubric(path: Path | None = None) -> str:
    rubric = path or RUBRIC_PATH
    if not rubric.is_file():
        raise FileNotFoundError(f"judge rubric not found: {rubric}")
    return rubric.read_text(encoding="utf-8")


def judge_evidence_scope(trial: TrialResult) -> list[str]:
    """Workspace-relative evidence the judge may cite for one trial."""

    paths: list[str] = []
    for step in trial.steps:
        paths.extend(step.changed_paths)
    return sorted(set(paths))


def judge_input_bundle(scenario: Scenario, trial: TrialResult) -> dict[str, Any]:
    """Bounded, structured input for a judge call (no raw event dumps)."""

    return {
        "scenario_id": scenario.scenario_id,
        "task_kind": scenario.kind,
        "messages": [
            {"step": step.index, "answer": step.answer[:2000]}
            for step in trial.steps
            if step.answer
        ],
        "changed_paths": judge_evidence_scope(trial),
        "deterministic_passed": trial.passed,
        "first_failure_step": trial.first_failure_step,
        "primary_failure": trial.primary_failure,
    }


class FakeJudge:
    """Deterministic advisory judge for CI and offline self-checks.

    规则刻意简单：回答覆盖了改动面且确定性结果通过 -> 4 分；确定性失败 ->
    低分并复述主因；引用了改动面之外的路径 -> uncertain。它证明裁判接口的
    输出形状与"裁判不能翻绿确定性失败"的边界，不评价语义质量。
    """

    def __init__(self, rubric_version: str = "v1") -> None:
        self.rubric_version = rubric_version

    def judge(
        self, scenario: Scenario, trial: TrialResult
    ) -> JudgeResult:
        bundle = judge_input_bundle(scenario, trial)
        answers = " ".join(item["answer"] for item in bundle["messages"]).casefold()
        out_of_scope = [
            path
            for path in bundle["changed_paths"]
            if path not in answers and path.split("/")[-1] not in answers
        ]
        if not trial.passed:
            return JudgeResult(
                score=1.0,
                reason=(
                    f"deterministic failure at step {trial.first_failure_step} "
                    f"({trial.primary_failure}); advisory only"
                ),
                evidence_paths=bundle["changed_paths"],
                uncertain=False,
                judge="fake",
                rubric_version=self.rubric_version,
            )
        if out_of_scope:
            return JudgeResult(
                score=3.0,
                reason="answers do not clearly ground every changed path",
                evidence_paths=out_of_scope,
                uncertain=True,
                judge="fake",
                rubric_version=self.rubric_version,
            )
        return JudgeResult(
            score=4.0,
            reason="answers cover the changed workspace paths; no contradiction found",
            evidence_paths=bundle["changed_paths"],
            uncertain=False,
            judge="fake",
            rubric_version=self.rubric_version,
        )
