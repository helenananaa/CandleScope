"""One transaction for multiple ordered, unpublished eight-actor phases."""

import asyncio

from .multi_commit import MutationGroup
from .timing import timed_to_thread


async def commit_actor_phases(service, phases, *, tape=False):
    if (not tape and len(phases) != 2) or (tape and not 2 <= len(phases) <= 16):
        raise ValueError("an atomic interval pair requires two phases")
    groups = [MutationGroup(phase["commands"]) for phase in phases]
    if tape:
        from .constants import CommandType
        if any(c.type is not CommandType.ADVANCE_BY for g in groups for c in g.commands.values()):
            raise ValueError("tape phases require exact duration commands")
    elif not all(group.batched_builders for group in groups):
        raise ValueError("only shared BAR interval commands can form an atomic pair")
    root = groups[0]
    if any(set(group.commands) != set(root.commands) for group in groups):
        raise ValueError("batch phases must contain the same actors")
    root.phases = groups
    root.terminal_only = tape
    for group, phase in zip(groups, phases, strict=True):
        group.defer_tape_projections = tape
        group.tape_summary = tape and bool(phase.get("tape_summary"))
        group.prepared_tape = phase.get("prepared_tape", {}) if group.tape_summary else {}
    registry = getattr(service, "_multi_mutation_groups", None)
    if registry is None:
        registry = service._multi_mutation_groups = {}
    if any(sid in registry for sid in root.commands):
        raise RuntimeError("overlapping actor phases")

    async def execute():
        root.command_records = await service.store.run_extension_read(
            lambda c: {sid: service.store._load_command_row(c, sid, cmd.command_id)
                       for sid, cmd in root.commands.items()}
        )
        if any(root.command_records.values()):
            raise ValueError("batch prefix already exists")
        registry.update({sid: root for sid in root.commands})
        tasks = [asyncio.create_task(service.command(sid, cmd, _training_internal=True))
                 for sid, cmd in root.commands.items()]
        waiters = []
        batches = []

        async def barrier(event):
            waiter = asyncio.create_task(event.wait())
            waiters.append(waiter)
            await asyncio.wait([waiter, *tasks], return_when=asyncio.FIRST_COMPLETED)
            if not event.is_set():
                errors = [t.exception() for t in tasks if t.done() and not t.cancelled()]
                raise next((e for e in errors if e is not None), RuntimeError("incomplete actor batch"))

        try:
            for ordinal, (group, phase) in enumerate(zip(groups, phases, strict=True)):
                if group.batched_builders:
                    await barrier(group.builders_ready)
                    await timed_to_thread("multi_builder_batch", lambda: [group.builders[sid]() for sid in group.commands])
                    group.builders_completed.set_result(None)
                await barrier(group.ready)
                if phase.get("prepare_candidates") is not None:
                    await timed_to_thread("multi_encode_records", phase["prepare_candidates"], group.mutations)
                rows = []
                for sid in group.commands:
                    m = group.mutations[sid]
                    rows.append(dict(
                        session_id=sid, command=m.command.to_dict(), accepted=True,
                        result=service._command_result_payload(m.result), error_code=None,
                        error_message=None, error_details=None, session_state=m.session_state,
                        checkpoint=m.checkpoint, source_events=m.source_events,
                        component_state=m.component_state, previous_component_state=m.previous_component_state,
                        history_frames=m.history_frames,
                    ))
                batches.append((rows, phase["before"], phase["after"]))
                if ordinal < len(groups)-1:
                    group.committed.set_result(None)  # candidate-only prefix
            await service.store.commit_command_phases(batches)
            groups[-1].committed.set_result(None)
            return await asyncio.gather(*tasks)
        except BaseException as error:
            for group in groups:
                for future in (group.builders_completed, group.committed):
                    if not future.done():
                        future.set_exception(error)
                        future.exception()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise
        finally:
            for waiter in waiters:
                waiter.cancel()
            await asyncio.gather(*waiters, return_exceptions=True)
            for sid in root.commands:
                registry.pop(sid, None)
            root.phases = None
            for group in groups:
                group.builders.clear()
                group.mutations.clear()
                group.command_records.clear()

    task = asyncio.create_task(execute())
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        await task
        raise
