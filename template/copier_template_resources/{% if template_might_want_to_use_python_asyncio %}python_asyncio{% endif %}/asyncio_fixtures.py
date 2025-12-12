import asyncio

import pytest
from backend_api.background_tasks import background_task_exceptions
from backend_api.background_tasks import background_tasks_set


async def _wait_for_tasks(tasks_list: list[asyncio.Task[None]]):
    _, pending = await asyncio.wait(tasks_list, timeout=5.0)
    if pending:
        raise RuntimeError(f"There are still pending tasks: {pending}")


@pytest.fixture(autouse=True)
def fail_on_background_task_errors():
    """Automatically fail tests if ANY background task raises an exception."""
    background_task_exceptions.clear()

    yield

    # Wait for background tasks to complete (using asyncio.run for sync fixture)
    if background_tasks_set:
        tasks_list = list(background_tasks_set)
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            asyncio.run(_wait_for_tasks(tasks_list))
        else:
            loop.run_until_complete(_wait_for_tasks(tasks_list))

    # Fail if any exceptions occurred
    if background_task_exceptions:
        pytest.fail(
            f"Background tasks raised {len(background_task_exceptions)} exception(s):\n"
            + "\n\n".join(f"{type(e).__name__}: {e}" for e in background_task_exceptions)
        )
