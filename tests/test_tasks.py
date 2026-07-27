# =============================================================================
# 任务服务测试 —— 验证导入任务事件存储
# =============================================================================

from pathlib import Path

import pytest

from cellwiki.domain.contracts import IngestStage, TaskStatus
from cellwiki.services.tasks import TaskEventRepository


def test_task_events_are_persisted_and_ordered(tmp_path: Path):
    repository = TaskEventRepository(tmp_path)

    repository.record(
        run_id="ingest_demo",
        source_id="src_demo",
        stage=IngestStage.SOURCE_READ,
        status=TaskStatus.RUNNING,
        message="Loading source.",
        progress=5,
    )
    repository.record(
        run_id="ingest_demo",
        source_id="src_demo",
        stage=IngestStage.HUMAN_REVIEW,
        status=TaskStatus.AWAITING_REVIEW,
        message="Ready for review.",
        progress=75,
        change_set_id="cs_demo",
    )

    events = repository.list_events("ingest_demo")
    assert [event.stage for event in events] == [IngestStage.SOURCE_READ, IngestStage.HUMAN_REVIEW]
    assert repository.list_runs()[0]["status"] == TaskStatus.AWAITING_REVIEW.value
    assert repository.list_runs(source_id="src_other") == []


def test_task_event_repository_rejects_path_like_run_ids(tmp_path: Path):
    repository = TaskEventRepository(tmp_path)

    with pytest.raises(ValueError):
        repository.list_events("..\\outside")
