"""Persistent workspace-memory job scheduling tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from cellwiki.services.agent_memory_jobs import MemoryJobStore
from cellwiki.services.runtime_store import RuntimeStore


def _store(tmp_path: Path) -> MemoryJobStore:
    runtime = RuntimeStore(tmp_path)
    return MemoryJobStore(runtime.path, tmp_path)


def test_upsert_thread_job_is_idempotent_and_refreshes(tmp_path: Path):
    jobs = _store(tmp_path)
    first_at = datetime(2026, 9, 29, 12, 0, tzinfo=UTC)
    second_at = first_at + timedelta(hours=1)

    first = jobs.upsert_thread_job(
        thread_id="thread_1",
        available_at=first_at,
        input_watermark="run_1",
    )
    second = jobs.upsert_thread_job(
        thread_id="thread_1",
        available_at=second_at,
        input_watermark="run_2",
        priority=1,
    )

    assert first.job_id == second.job_id
    assert second.available_at == second_at
    assert second.priority == 1
    assert second.input_watermark == "run_2"
    assert len(jobs.list_jobs()) == 1


def test_claim_leases_due_job_and_recovers_expired_lease(tmp_path: Path):
    jobs = _store(tmp_path)
    now = datetime(2026, 9, 29, 12, 0, tzinfo=UTC)
    jobs.upsert_thread_job(
        thread_id="thread_1",
        available_at=now - timedelta(minutes=1),
        input_watermark="run_1",
    )

    first = jobs.claim_thread_jobs(
        now=now,
        worker_id="worker_1",
        lease_seconds=60,
        limit=5,
    )
    duplicate = jobs.claim_thread_jobs(
        now=now,
        worker_id="worker_2",
        lease_seconds=60,
        limit=5,
    )
    recovered = jobs.claim_thread_jobs(
        now=now + timedelta(seconds=61),
        worker_id="worker_3",
        lease_seconds=60,
        limit=5,
    )

    assert [job.job_id for job in first] == [first[0].job_id]
    assert duplicate == []
    assert len(recovered) == 1
    assert recovered[0].job_id == first[0].job_id
    assert recovered[0].worker_id == "worker_3"


def test_retry_backoff_and_terminal_failure(tmp_path: Path):
    jobs = _store(tmp_path)
    now = datetime(2026, 9, 29, 12, 0, tzinfo=UTC)
    job = jobs.upsert_thread_job(
        thread_id="thread_1",
        available_at=now,
        input_watermark="run_1",
    )
    claimed = jobs.claim_thread_jobs(
        now=now,
        worker_id="worker_1",
        lease_seconds=60,
        limit=1,
    )[0]
    assert claimed.job_id == job.job_id

    jobs.fail(
        job.job_id,
        error="temporary",
        retry_at=now + timedelta(minutes=1),
        max_retries=2,
    )
    retrying = jobs.get_job(job.job_id)
    assert retrying is not None
    assert retrying.retry_count == 1
    assert retrying.retry_at == now + timedelta(minutes=1)
    assert jobs.claim_thread_jobs(
        now=now,
        worker_id="worker_2",
        lease_seconds=60,
        limit=1,
    ) == []

    jobs.fail(
        job.job_id,
        error="still failing",
        retry_at=now + timedelta(minutes=2),
        max_retries=2,
    )
    terminal = jobs.get_job(job.job_id)
    assert terminal is not None
    assert terminal.retry_count == 2
    assert terminal.retry_at is None
    assert jobs.claim_thread_jobs(
        now=now + timedelta(hours=1),
        worker_id="worker_3",
        lease_seconds=60,
        limit=1,
    ) == []
