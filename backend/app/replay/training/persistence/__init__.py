"""Training persistence operations; transactions belong to ReplaySQLiteStore.

Functions receive the caller-owned SQLite connection. They never start or commit
a transaction, publish actor state, or import the TrainingRunStore facade.
"""
