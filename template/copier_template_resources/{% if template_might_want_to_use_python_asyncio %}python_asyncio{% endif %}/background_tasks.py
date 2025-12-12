import asyncio
import logging
import traceback
from collections import deque
from weakref import WeakSet

logger = logging.getLogger(__name__)
background_tasks_set: WeakSet[asyncio.Task[None]] = WeakSet()
background_task_exceptions: deque[Exception] = deque(
    maxlen=100  # don't grow infinitely in production
)
# Store creation tracebacks for debugging
_task_creation_tracebacks: dict[int, str] = {}


def _task_done_callback(task: asyncio.Task[None]):
    task_id = id(task)
    background_tasks_set.discard(task)
    try:
        task.result()
    except (  # pragma: no cover # hard to unit test this, but it'd be good to think of a way to do so
        asyncio.CancelledError
    ):
        _ = _task_creation_tracebacks.pop(task_id, None)
        return
    except Exception as e:  # pragma: no cover # hard to unit test this, but it'd be good to think of a way to do so
        creation_tb = _task_creation_tracebacks.pop(task_id, "No traceback available")
        logger.exception(f"Unhandled exception in background task\nTask was created from:\n{creation_tb}")
        background_task_exceptions.append(e)
    else:
        # Clean up on successful completion
        _ = _task_creation_tracebacks.pop(task_id, None)


def register_task(task: asyncio.Task[None]) -> None:
    # Capture the stack trace at task creation time (excluding this function)
    creation_stack = "".join(traceback.format_stack()[:-1])
    _task_creation_tracebacks[id(task)] = creation_stack

    background_tasks_set.add(task)
    task.add_done_callback(_task_done_callback)
