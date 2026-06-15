import pytest

from app.schemas.enums import TaskStatus
from app.services.transitions import can_transition

VALID = [
    (TaskStatus.NEW, TaskStatus.PENDING),
    (TaskStatus.NEW, TaskStatus.CANCELLED),
    (TaskStatus.NEW, TaskStatus.FAILED),
    (TaskStatus.PENDING, TaskStatus.IN_PROGRESS),
    (TaskStatus.PENDING, TaskStatus.CANCELLED),
    (TaskStatus.PENDING, TaskStatus.FAILED),
    (TaskStatus.IN_PROGRESS, TaskStatus.COMPLETED),
    (TaskStatus.IN_PROGRESS, TaskStatus.FAILED),
]

INVALID = [
    (TaskStatus.NEW, TaskStatus.IN_PROGRESS),
    (TaskStatus.NEW, TaskStatus.COMPLETED),
    (TaskStatus.PENDING, TaskStatus.COMPLETED),
    (TaskStatus.IN_PROGRESS, TaskStatus.CANCELLED),
    (TaskStatus.IN_PROGRESS, TaskStatus.PENDING),
    (TaskStatus.COMPLETED, TaskStatus.PENDING),
    (TaskStatus.FAILED, TaskStatus.IN_PROGRESS),
    (TaskStatus.CANCELLED, TaskStatus.PENDING),
    (TaskStatus.COMPLETED, TaskStatus.FAILED),
]


@pytest.mark.parametrize(("old", "new"), VALID)
def test_valid_transitions_allowed(old: TaskStatus, new: TaskStatus) -> None:
    assert can_transition(old, new) is True


@pytest.mark.parametrize(("old", "new"), INVALID)
def test_invalid_transitions_rejected(old: TaskStatus, new: TaskStatus) -> None:
    assert can_transition(old, new) is False


@pytest.mark.parametrize("terminal", [TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED])
def test_terminal_states_have_no_outgoing(terminal: TaskStatus) -> None:
    assert all(not can_transition(terminal, target) for target in TaskStatus)


def test_new_to_failed_allowed() -> None:
    assert can_transition(TaskStatus.NEW, TaskStatus.FAILED) is True


def test_pending_to_failed_allowed() -> None:
    assert can_transition(TaskStatus.PENDING, TaskStatus.FAILED) is True
