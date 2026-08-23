# =============================================================================
# 日志上下文测试 —— 验证运行关联上下文的正确性
# =============================================================================

"""Tests for logging context management and run correlation."""

import logging


from cellwiki.services.logging_context import (
    ContextFilter,
    get_log_context,
    log_context,
    setup_structured_logging,
)


def test_log_context_binds_and_unbinds_fields():
    """Verify that log_context temporarily binds fields and restores previous state."""
    assert get_log_context() == {}
    
    with log_context(run_id="run_123", thread_id="thread_456"):
        context = get_log_context()
        assert context["run_id"] == "run_123"
        assert context["thread_id"] == "thread_456"
    
    # Context should be restored after exiting
    assert get_log_context() == {}


def test_log_context_nesting():
    """Verify that nested log_context calls merge and restore correctly."""
    with log_context(run_id="run_outer"):
        assert get_log_context()["run_id"] == "run_outer"
        
        with log_context(thread_id="thread_inner"):
            context = get_log_context()
            assert context["run_id"] == "run_outer"
            assert context["thread_id"] == "thread_inner"
        
        # Inner context should be restored
        assert get_log_context() == {"run_id": "run_outer"}


def test_context_filter_injects_fields_into_log_record():
    """Verify that ContextFilter adds context fields to log records."""
    filter_obj = ContextFilter()
    
    # Create a log record
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="Test message",
        args=(),
        exc_info=None,
    )
    
    # Without context, fields should default to "-"
    filter_obj.filter(record)
    assert record.run_id == "-"
    assert record.thread_id == "-"
    
    # With context, fields should be populated
    with log_context(run_id="run_test", thread_id="thread_test", project_id="proj_test"):
        record2 = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg="Test message",
            args=(),
            exc_info=None,
        )
        filter_obj.filter(record2)
        assert record2.run_id == "run_test"
        assert record2.thread_id == "thread_test"
        assert record2.project_id == "proj_test"


def test_setup_structured_logging_adds_filter():
    """Verify that setup_structured_logging adds ContextFilter to handlers."""
    # Create a test logger with a handler
    logger = logging.getLogger("test_structured")
    logger.handlers.clear()
    handler = logging.StreamHandler()
    logger.addHandler(handler)
    
    # Setup structured logging
    setup_structured_logging(level="DEBUG")
    
    # Verify filter was added
    root = logging.getLogger()
    assert any(isinstance(f, ContextFilter) for f in root.handlers[0].filters)
