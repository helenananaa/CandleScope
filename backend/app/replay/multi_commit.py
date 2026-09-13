"""Coordinator-owned actor candidates with a single durable commit barrier."""

from __future__ import annotations

import asyncio
from time import perf_counter
from .timing import record_timing, timed_to_thread
from .internal_commands import InternalCommandType


class MutationGroup:
    def __init__(self, commands):
        commands = tuple(commands)
        self.commands = dict(commands)
        if not commands or len(self.commands) != len(commands):
            raise ValueError("group requires unique nonempty actor identities")
        self.command_records = {}
        self.mutations = {}
        self.ready = asyncio.Event()
        self.committed = asyncio.get_running_loop().create_future()
        self.batched_builders = all(
            c.type is InternalCommandType.MULTI_SHARED_INDEXED_INTERVAL
            for _, c in commands
        )
        self.builders = {}
        self.builders_ready = asyncio.Event()
        self.builders_completed = asyncio.get_running_loop().create_future()

    async def prepare(self, session_id, work):
        if session_id not in self.commands or session_id in self.builders:
            raise ValueError("invalid grouped builder identity")
        self.builders[session_id] = work
        if len(self.builders) == len(self.commands):
            self.builders_ready.set()
        await asyncio.shield(self.builders_completed)

    def matches(self, mutation):
        command = self.commands.get(mutation.session_id)
        return mutation.command is not None and command == mutation.command

    async def stage(self, mutation):
        if mutation.error is not None:
            raise mutation.error
        if mutation.session_id in self.mutations:
            raise ValueError("multi-actor candidate was rejected or duplicated")
        self.mutations[mutation.session_id] = mutation
        if len(self.mutations) == len(self.commands):
            self.ready.set()
        await asyncio.shield(self.committed)


async def commit_actor_commands(service, commands, *, before, after, prepare_candidates=None):
    """No actor publishes or acknowledges until all durable candidates commit.

    Cancellation drains the transaction and actor publications first. A pre-commit
    error releases every staged actor through its normal rollback path.
    """

    commands = tuple(commands)

    async def execute():
        group = MutationGroup(commands)
        registry = getattr(service, "_multi_mutation_groups", None)
        if registry is None:
            registry = service._multi_mutation_groups = {}
        if any(session in registry for session in group.commands):
            raise RuntimeError("overlapping multi-actor transaction")
        group.command_records = await service.store.run_extension_read(
            lambda connection: {
                session: service.store._load_command_row(
                    connection, session, command.command_id
                )
                for session, command in commands
            }
        )
        registry.update({session: group for session in group.commands})
        candidates_started = perf_counter()
        tasks = [
            asyncio.create_task(
                service.command(session, command, _training_internal=True)
            )
            for session, command in commands
        ]
        ready = asyncio.create_task(group.ready.wait())
        builders_ready = asyncio.create_task(group.builders_ready.wait())
        try:
            if group.batched_builders:
                await asyncio.wait(
                    [builders_ready, *tasks], return_when=asyncio.FIRST_COMPLETED
                )
                if not group.builders_ready.is_set():
                    errors = [
                        t.exception() for t in tasks if t.done() and not t.cancelled()
                    ]
                    raise next(
                        (e for e in errors if e is not None),
                        RuntimeError("actor completed before builder barrier"),
                    )

                def build_all():
                    for session, _ in commands:
                        group.builders[session]()

                await timed_to_thread("multi_builder_batch", build_all)
                group.builders_completed.set_result(None)
            await asyncio.wait([ready, *tasks], return_when=asyncio.FIRST_COMPLETED)
            if not group.ready.is_set():
                errors = [
                    task.exception()
                    for task in tasks
                    if task.done() and not task.cancelled()
                ]
                raise next(
                    (error for error in errors if error is not None),
                    RuntimeError("actor completed without a group candidate"),
                )
            record_timing("multi_candidates", candidates_started)
            if prepare_candidates is not None:
                await timed_to_thread("multi_encode_records", prepare_candidates, group.mutations)
            rows = []
            for session, _command in commands:
                m = group.mutations[session]
                rows.append(
                    dict(
                        session_id=session,
                        command=m.command.to_dict(),
                        accepted=True,
                        result=service._command_result_payload(m.result),
                        error_code=None,
                        error_message=None,
                        error_details=None,
                        session_state=m.session_state,
                        checkpoint=m.checkpoint,
                        source_events=m.source_events,
                        component_state=m.component_state,
                        previous_component_state=m.previous_component_state,
                        history_frames=m.history_frames,
                    )
                )
            sql_started = perf_counter()
            await service.store.commit_command_group(rows, before=before, after=after)
            record_timing("multi_sql_batch", sql_started)
            group.committed.set_result(None)
            publish_started = perf_counter()
            results = await asyncio.gather(*tasks)
            record_timing("multi_publish", publish_started)
            return results
        except BaseException as exc:
            if not group.builders_completed.done():
                group.builders_completed.set_exception(exc)
                group.builders_completed.exception()
            if not group.committed.done():
                group.committed.set_exception(exc)
                # Consume the exception even if no actor reached its hook.
                group.committed.exception()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise
        finally:
            ready.cancel()
            builders_ready.cancel()
            await asyncio.gather(ready, builders_ready, return_exceptions=True)
            for session in group.commands:
                registry.pop(session, None)
            # An idle actor can retain its last request. Do not let that small
            # request keep every actor's builders/checkpoints alive with it.
            group.builders.clear()
            group.mutations.clear()
            group.command_records.clear()

    task = asyncio.create_task(execute())
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        await task
        raise
