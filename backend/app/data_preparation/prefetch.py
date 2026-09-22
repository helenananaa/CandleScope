"""Bounded, opt-in anticipation based on repeated user preparation requests."""
from .models import PreparationRequest, Requirement, fingerprint


def next_prefetch(jobs, *, now_ms):
    """One future day for a BAR market used at least twice in the last week.

    Only completed historical minutes are eligible. Trades and auxiliary inputs
    are deliberately excluded from speculative network and storage spending.
    """
    groups = {}
    for job in jobs:
        if (job["state"] != "READY" or job["request"]["consumer"] == "PREFETCH"
                or job["created_ms"] < now_ms - 7 * 86_400_000):
            continue
        seen = set()
        for raw in job["request"]["requirements"]:
            req = Requirement.model_validate(raw)
            if req.role != "BARS":
                continue
            identity = (req.exchange, req.market_type, req.symbol, req.interval)
            if identity in seen:
                continue
            groups.setdefault(identity, []).append(req)
            seen.add(identity)
    existing = {job["idempotency_key"] for job in jobs}
    for requirements in groups.values():
        if len(requirements) < 2:
            continue
        latest = max(requirements, key=lambda item: item.end_ms)
        end = min(latest.end_ms + 86_400_000, now_ms // 60_000 * 60_000)
        if end <= latest.end_ms:
            continue
        target = latest.model_copy(update={"start_ms": latest.end_ms, "end_ms": end})
        key = "prefetch-v1:" + fingerprint(target.model_dump())
        if key in existing:
            continue
        return PreparationRequest(idempotency_key=key, consumer="PREFETCH", requirements=[target],
                                  max_bytes=16 * 1024**2)
    return None
