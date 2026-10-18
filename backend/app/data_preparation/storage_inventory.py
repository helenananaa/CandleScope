"""Cancellable physical inventory; inspect each regular file once.

Reuse DirEntry metadata while walking the scope. In-scope observations update
one ledger in batches; missing and out-of-scope old paths are still rechecked.
A failed or interrupted scan cannot certify capacity.
"""

import os
import stat

from app.data_preparation.models import PreparationError


def reconcile(repository, stop):
    generation = repository.begin_inventory()
    try:
        abandoned = repository.abandoned_publications()
        unchecked = repository.publication_paths()
        batch = []

        def checkpoint():
            if stop.is_set():
                raise PreparationError(
                    "STORAGE_INVENTORY_INTERRUPTED",
                    "Storage inventory was interrupted",
                    retryable=True,
                )

        def observe(name, kind, observed):
            if not stat.S_ISREG(observed.st_mode):
                return
            unchecked.discard(name)
            batch.append((name, kind, observed.st_size, repository.now()))
            if len(batch) >= 2048:
                repository.register_inventoried_publications(batch)
                batch.clear()

        for root, kind in repository.publication_scopes():
            checkpoint()
            try:
                observed = root.stat(follow_symlinks=False)
            except FileNotFoundError:
                continue
            if stat.S_ISREG(observed.st_mode):
                observe(str(root), kind, observed)
                continue
            if not stat.S_ISDIR(observed.st_mode):
                continue
            pending = [str(root)]
            while pending:
                checkpoint()
                directory = pending.pop()
                try:
                    entries = os.scandir(directory)
                except FileNotFoundError:
                    # Background metadata retention may retire a directory
                    # after its parent was visited. Missing paths are rechecked
                    # against the publication ledger below.
                    continue
                with entries:
                    for entry in entries:
                        checkpoint()
                        if entry.is_symlink():
                            continue
                        if entry.is_dir(follow_symlinks=False):
                            if not getattr(os.path, "isjunction", lambda _: False)(
                                entry.path
                            ):
                                pending.append(entry.path)
                        elif entry.is_file(follow_symlinks=False):
                            try:
                                observe(
                                    entry.path, kind, entry.stat(follow_symlinks=False)
                                )
                            except FileNotFoundError:
                                pass
        repository.register_inventoried_publications(batch)
        checkpoint()
        missing = repository.refresh_publications(stop=stop, paths=unchecked)
        repository.forget_missing_publications(missing)
        repository.reconcile_trade_receipts(stop=stop)
        repository.reconcile_abandoned_publications(abandoned)
        repository.finish_inventory(generation, "READY")
    except BaseException:
        repository.finish_inventory(generation, "INCOMPLETE")
        raise
