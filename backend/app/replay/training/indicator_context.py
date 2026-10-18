"""Bridge bounded indicator workers to the existing asynchronous history owner."""

from __future__ import annotations

import time
from concurrent.futures import Future
from threading import Event

from app.data_preparation.models import PreparationError
from app.replay.display_time import SourceBucketTimeMapper
from app.replay.models import ReplaySessionConfig

from .errors import TrainingRunError
from .history import _decode_bar_snapshot, _progressive_repository, build_history_page


def await_context(coroutine, *, loop, cancelled):
    """Called only from the owned calculation worker, never the event loop."""
    result, finished, owned = Future(), Event(), []

    def complete(task):
        try:
            if task.cancelled():
                result.set_exception(
                    InterruptedError("indicator preparation cancelled")
                )
            else:
                failure = task.exception()
                if failure is not None:
                    result.set_exception(failure)
                else:
                    result.set_result(task.result())
        finally:
            finished.set()

    def start():
        task = loop.create_task(coroutine)
        owned.append(task)
        task.add_done_callback(complete)

    loop.call_soon_threadsafe(start)
    cancellation_sent = False
    try:
        while not finished.wait(0.05):
            if cancelled.is_set() and not cancellation_sent:
                # start() is ordered before this callback. Wait for the actual
                # task's cleanup, not just a cancelled concurrent Future.
                loop.call_soon_threadsafe(lambda: owned[0].cancel())
                cancellation_sent = True
        return result.result()
    except PreparationError as exc:
        raise TrainingRunError(
            exc.code, str(exc), status_code=503, details={"retryable": exc.retryable}
        ) from exc


def attach_context_history(history, context, *, loop, cancelled):
    args = history.arguments
    binding, persisted = args["binding"], args["persisted"]
    repository, _ = _progressive_repository(
        persisted, args["repository"], args["progressive_history_factory"]
    )
    origin = await_context(
        context.origin(
            binding=binding, persisted=persisted, repository=repository, discover=True
        ),
        loop=loop,
        cancelled=cancelled,
    )
    snapshot = _decode_bar_snapshot(
        persisted, config=ReplaySessionConfig.from_dict(binding["config"])
    )
    mapper = SourceBucketTimeMapper.create(
        interval=history.interval,
        actual_replay_start_ms=int(binding["history_policy"]["actual_replay_start_ms"]),
        public_replay_start_ms=snapshot.replay_start_ms,
        source_bucket_anchor_ms=binding.get("display_source_bucket_anchor_ms"),
    )
    history.origin_ms = context.public_origin(origin, mapper)
    history.history_epoch = context.context_epoch(history.history_epoch, origin)
    history.identity = {
        **history.identity,
        "origin_ms": history.origin_ms,
        "history_epoch": history.history_epoch,
    }
    deadline = time.monotonic() + context.wait_seconds

    def page_loader(**kwargs):
        expected = kwargs.pop("expected_history_epoch")
        page = build_history_page(**kwargs, expected_history_epoch=None)
        return await_context(
            context.extend(
                page=page,
                binding=binding,
                persisted=persisted,
                repository=repository,
                before_ms=kwargs["before_ms"],
                limit=kwargs["limit"],
                expected_history_epoch=expected,
                origin=origin,
                deadline=deadline,
            ),
            loop=loop,
            cancelled=cancelled,
        )

    history.page_loader = page_loader
    return origin
