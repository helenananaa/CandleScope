"""Cancellable background reconciliation of durable publication directories."""
import os
from pathlib import Path

from .models import PreparationError


def reconcile(repository, stop):
    generation = repository.begin_inventory()
    try:
        abandoned = repository.abandoned_publications()
        repository.refresh_publications(stop=stop)
        batch = []
        def checkpoint():
            if stop.is_set():
                raise PreparationError("STORAGE_INVENTORY_INTERRUPTED", "Storage inventory was interrupted", retryable=True)
        def failed(error):
            raise error
        for root, kind in repository.publication_scopes():
            checkpoint()
            if not root.exists():
                continue
            if root.is_file():
                repository.register_publications([(root, kind)])
                continue
            for directory, children, filenames in os.walk(root, followlinks=False, onerror=failed):
                checkpoint()
                children[:] = [name for name in children if not (Path(directory) / name).is_symlink()
                    and not getattr(os.path, "isjunction", lambda _: False)(Path(directory) / name)]
                for name in filenames:
                    checkpoint()
                    path = Path(directory) / name
                    if path.is_symlink():
                        continue
                    batch.append((path, kind))
                    if len(batch) >= 256:
                        repository.register_publications(batch)
                        batch.clear()
        repository.register_publications(batch)
        repository.reconcile_trade_receipts(stop=stop)
        repository.reconcile_abandoned_publications(abandoned)
        repository.finish_inventory(generation, "READY")
    except BaseException:
        repository.finish_inventory(generation, "INCOMPLETE")
        raise
