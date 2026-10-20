"""Compare known additive Workbench defaults without rewriting frozen records.

Only the reviewed defaults introduced by WorkbenchBarSettings are aliases for
absence. Other fields, values and number types keep their original identity.
"""

_DEFAULTS = (
    ("cost_sensitivity_mode", "AUTO"),
    ("account_model", None),
    ("leverage", 1),
    ("funding_mode", "OFF"),
    ("account_data", None),
    ("execution_model_revision", None),
    ("participation_rate", None),
    ("bar_path_scenario", None),
)
_MISSING = object()


def _without_defaults(value):
    result = dict(value)
    for field, default in _DEFAULTS:
        if result.get(field, _MISSING) == default:
            result.pop(field)
    return result


def request_identity(value):
    if not isinstance(value, dict) or value.get("execution_mode") != "CANDLESCOPE":
        return value
    return _without_defaults(value)


def preparation_identity(value, *, field):
    if not isinstance(value, dict) or not isinstance(value.get(field), dict):
        return value
    result = dict(value)
    result[field] = (
        request_identity(value[field])
        if field == "run"
        else _without_defaults(value[field])
    )
    return result
