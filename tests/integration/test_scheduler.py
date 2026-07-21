"""Integration tests for scheduler service."""
from services.scheduler import get_state, SchedulerState


def test_scheduler_state_initial():
    """Test scheduler state initialization."""
    state = get_state()
    assert isinstance(state, SchedulerState)
    assert state.last_check_count == 0
    assert state.last_check_errors == []
