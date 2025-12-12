import asyncio
import logging
import traceback
from collections import deque
from weakref import WeakKeyDictionary
from weakref import WeakSet

logger = logging.getLogger(__name__)
background_tasks_set: WeakSet[asyncio.Task[None]] = WeakSet()
background_task_exceptions: deque[Exception] = deque(
    maxlen=100  # don't grow infinitely in production
)
# Store creation tracebacks for debugging
_task_creation_tracebacks: WeakKeyDictionary[asyncio.Task[None], str] = WeakKeyDictionary()


def _task_done_callback(task: asyncio.Task[None]):
    background_tasks_set.discard(task)
    task_creation_traceback = _task_creation_tracebacks.pop(task, None)
    try:
        task.result()
    except (  # pragma: no cover # hard to unit test this, but it'd be good to think of a way to do so
        asyncio.CancelledError
    ):
        return
    except Exception as e:  # pragma: no cover # hard to unit test this, but it'd be good to think of a way to do so
        logger.exception(f"Unhandled exception in background task\nTask was created from:\n{task_creation_traceback}")
        background_task_exceptions.append(e)


def register_task(task: asyncio.Task[None]) -> None:
    # Capture the stack trace at task creation time (excluding this function)
    creation_stack = "".join(traceback.format_stack()[:-1])
    _task_creation_tracebacks[task] = creation_stack

    background_tasks_set.add(task)
    task.add_done_callback(_task_done_callback)
