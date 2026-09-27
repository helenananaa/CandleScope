"""Repositories share the one ReplaySQLiteStore worker and transaction owner.

They own operation groups, never a second database connection or commit policy.
"""
