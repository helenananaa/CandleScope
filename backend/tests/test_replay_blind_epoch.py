from app.replay.errors import ReplayDomainError, ReplayErrorCode
from app.replay.service import ReplayService


def test_blind_catalog_retry_preserves_only_the_safe_reason():
    error = ReplayDomainError(
        ReplayErrorCode.DATASET_MISMATCH,
        "private source at 2026-08-01",
        details={"reason": "CATALOG_EPOCH_MISMATCH", "path": "private.parquet", "start_ms": 1234},
    )
    safe = ReplayService._blind_safe_dataset_error(True, error)
    assert safe.details == {"blind_redacted": True, "reason": "CATALOG_EPOCH_MISMATCH"}
    assert safe.message == "blind replay dataset validation failed"
    assert ReplayService._recovery_error(error, blind_mode=True).details == {"blind_redacted": True}


def test_other_blind_dataset_reasons_stay_redacted():
    error = ReplayDomainError(
        ReplayErrorCode.DATASET_MISMATCH,
        "private source",
        details={"reason": "SOURCE_REVISION_CHANGED", "path": "private.parquet"},
    )
    safe = ReplayService._blind_safe_dataset_error(True, error)
    assert safe.details == {"blind_redacted": True}
