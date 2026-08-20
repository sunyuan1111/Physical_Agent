from __future__ import annotations

import json
import re
from typing import Any, Literal


ExpectationStatus = Literal["verified", "violated", "skipped"]

EXPECTED_MAX_CHECKS = 20
EXPECTED_MAX_BYTES = 8192
EXPECTED_JSON_SCHEMA: dict[str, Any] = {
    "type": "array",
    "maxItems": EXPECTED_MAX_CHECKS,
    "items": {
        "type": "object",
        "additionalProperties": True,
        "required": ["path", "op", "value"],
        "properties": {
            "path": {"type": "string"},
            "op": {"type": "string", "enum": ["eq", "ne", "in", "range"]},
            "value": {},
            "tolerance": {"type": "number"},
            "units": {"type": "string"},
            "description": {"type": "string"},
            "severity": {"type": "string"},
        },
    },
}

_SUPPORTED_OPS = {"eq", "ne", "in", "range"}
_STATE_KEYS = {"robots", "objects", "environment", "artifacts", "raw"}
_SELECTOR_RE = re.compile(r"^(?P<base>[A-Za-z0-9_-]+)\[(?P<key>[A-Za-z0-9_-]+)=(?P<value>[^\]]+)\]$")


def normalize_expected_metadata(metadata: dict[str, Any] | None) -> dict[str, Any]:
    normalized = dict(metadata or {})
    if "expected" not in normalized:
        return normalized
    normalized["expected"] = normalize_expected_value(normalized.get("expected"))
    return normalized


def normalize_expected_value(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    if isinstance(value, dict):
        items: list[Any] = [value]
    elif isinstance(value, list):
        if not value:
            return []
        items = list(value)
    else:
        items = [_invalid_check(f"expected must be a list or object; got {type(value).__name__}")]

    truncated = False
    if len(items) > EXPECTED_MAX_CHECKS:
        truncated = True
        items = items[: max(0, EXPECTED_MAX_CHECKS - 1)]
    checks = [_normalize_check(item) for item in items]
    if truncated:
        checks.append(
            _invalid_check(
                f"expected check list exceeded {EXPECTED_MAX_CHECKS} items and was truncated"
            )
        )

    if _stable_json_len(checks) <= EXPECTED_MAX_BYTES:
        return checks
    return [
        _invalid_check(
            f"expected metadata exceeded {EXPECTED_MAX_BYTES} serialized bytes and was truncated"
        )
    ]


def evaluate_expected(
    expected: Any,
    world: Any,
    feedback: dict[str, Any] | None = None,
) -> dict[str, Any]:
    checks = [
        _evaluate_check(check, world=world, feedback=feedback, index=index)
        for index, check in enumerate(normalize_expected_value(expected))
    ]
    status = aggregate_status([check["status"] for check in checks])
    message = _aggregate_message(status, checks)
    return {
        "status": status,
        "message": message,
        "expected": [check["expected"] for check in checks],
        "actual": [
            {
                "path": check.get("path"),
                "value": check.get("actual"),
                "status": check["status"],
            }
            for check in checks
        ],
        "checks": checks,
    }


def aggregate_status(statuses: list[str]) -> ExpectationStatus:
    if any(status == "violated" for status in statuses):
        return "violated"
    if any(status == "skipped" for status in statuses):
        return "skipped"
    return "verified"


def stable_json(value: Any) -> str:
    return json.dumps(_json_safe(value), ensure_ascii=False, sort_keys=True)


def _normalize_check(item: Any) -> dict[str, Any]:
    if not isinstance(item, dict):
        return _invalid_check(f"expected check must be an object; got {type(item).__name__}")
    return _limit_value(_json_safe(dict(item)))


def _invalid_check(reason: str) -> dict[str, Any]:
    return {"_invalid": reason}


def _evaluate_check(
    check: dict[str, Any],
    *,
    world: Any,
    feedback: dict[str, Any] | None,
    index: int,
) -> dict[str, Any]:
    if check.get("_invalid"):
        return _check_result(
            "skipped",
            check,
            actual=None,
            path=None,
            op=None,
            message=str(check["_invalid"]),
        )

    path = check.get("path")
    op = str(check.get("op") or "").strip().lower()
    if not isinstance(path, str) or not path.strip():
        return _check_result(
            "skipped",
            check,
            actual=None,
            path=None,
            op=op or None,
            message=f"Expected check {index + 1} is missing a non-empty path.",
        )
    if op not in _SUPPORTED_OPS:
        return _check_result(
            "skipped",
            check,
            actual=None,
            path=path,
            op=op or None,
            message=f"Expected check `{path}` uses unsupported op `{op or '<missing>'}`.",
        )

    found, actual, reason = _resolve_path(world, path)
    if not found:
        return _check_result(
            "skipped",
            check,
            actual=None,
            path=path,
            op=op,
            message=f"Expected path `{path}` could not be resolved: {reason}.",
        )

    value = check.get("value")
    tolerance = check.get("tolerance")
    status, message = _compare(path=path, op=op, actual=actual, expected=value, tolerance=tolerance)
    return _check_result(status, check, actual=actual, path=path, op=op, message=message)


def _compare(
    *,
    path: str,
    op: str,
    actual: Any,
    expected: Any,
    tolerance: Any,
) -> tuple[ExpectationStatus, str]:
    if op == "eq":
        equal, reason = _equal(actual, expected, tolerance)
        if reason:
            return "skipped", f"Expected `{path}` eq check skipped: {reason}."
        if equal:
            return "verified", f"Expected `{path}` to equal {stable_json(expected)}; actual was {stable_json(actual)}."
        return "violated", f"Expected `{path}` to equal {stable_json(expected)}; actual was {stable_json(actual)}."

    if op == "ne":
        equal, reason = _equal(actual, expected, tolerance)
        if reason:
            return "skipped", f"Expected `{path}` ne check skipped: {reason}."
        if not equal:
            return "verified", f"Expected `{path}` to differ from {stable_json(expected)}; actual was {stable_json(actual)}."
        return "violated", f"Expected `{path}` to differ from {stable_json(expected)}; actual was {stable_json(actual)}."

    if op == "in":
        if not isinstance(expected, list):
            return "skipped", f"Expected `{path}` in check requires list value."
        if actual in expected:
            return "verified", f"Expected `{path}` to be in {stable_json(expected)}; actual was {stable_json(actual)}."
        return "violated", f"Expected `{path}` to be in {stable_json(expected)}; actual was {stable_json(actual)}."

    minimum, maximum, range_reason = _range_bounds(expected)
    actual_number = _number(actual)
    tolerance_number = _number(tolerance) if tolerance is not None else 0.0
    if range_reason:
        return "skipped", f"Expected `{path}` range check skipped: {range_reason}."
    if actual_number is None:
        return "skipped", f"Expected `{path}` range check requires numeric actual value."
    if tolerance_number is None:
        return "skipped", f"Expected `{path}` range check requires numeric tolerance."
    low = minimum - tolerance_number
    high = maximum + tolerance_number
    if low <= actual_number <= high:
        return "verified", f"Expected `{path}` to be in range [{minimum}, {maximum}]; actual was {stable_json(actual)}."
    return "violated", f"Expected `{path}` to be in range [{minimum}, {maximum}]; actual was {stable_json(actual)}."


def _equal(actual: Any, expected: Any, tolerance: Any) -> tuple[bool, str | None]:
    if tolerance is None:
        return actual == expected, None
    actual_number = _number(actual)
    expected_number = _number(expected)
    tolerance_number = _number(tolerance)
    if actual_number is None or expected_number is None:
        return False, "tolerance requires numeric actual and expected values"
    if tolerance_number is None:
        return False, "tolerance must be numeric"
    return abs(actual_number - expected_number) <= tolerance_number, None


def _range_bounds(value: Any) -> tuple[float, float, str | None]:
    if isinstance(value, dict):
        minimum = _number(value.get("min"))
        maximum = _number(value.get("max"))
    elif isinstance(value, list) and len(value) == 2:
        minimum = _number(value[0])
        maximum = _number(value[1])
    else:
        return 0.0, 0.0, "value must be [min, max] or {'min': ..., 'max': ...}"
    if minimum is None or maximum is None:
        return 0.0, 0.0, "range bounds must be numeric"
    if minimum > maximum:
        return 0.0, 0.0, "range min must be <= max"
    return minimum, maximum, None


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _resolve_path(world: Any, path: str) -> tuple[bool, Any, str]:
    tokens = [token.strip() for token in path.strip().split(".") if token.strip()]
    if not tokens:
        return False, None, "path is empty"
    if tokens[0] == "world":
        tokens = tokens[1:]
    if not tokens:
        return False, None, "path only points at the world root"

    root = _json_safe(world)
    first_base = _token_base(tokens[0])
    if isinstance(root, dict) and first_base in _STATE_KEYS and first_base not in root:
        state = root.get("state")
        if isinstance(state, dict):
            root = state

    current: Any = root
    for token in tokens:
        found, current, reason = _resolve_token(current, token)
        if not found:
            return False, None, reason
    return True, _json_safe(current), ""


def _resolve_token(value: Any, token: str) -> tuple[bool, Any, str]:
    match = _SELECTOR_RE.match(token)
    if match:
        found, base_value, reason = _resolve_token(value, match.group("base"))
        if not found:
            return False, None, reason
        return _resolve_selector(base_value, match.group("key"), match.group("value"))

    if isinstance(value, dict):
        if token in value:
            return True, value[token], ""
        return False, None, f"key `{token}` is missing"
    if isinstance(value, list):
        try:
            index = int(token)
        except ValueError:
            return False, None, f"list index `{token}` is not an integer"
        if 0 <= index < len(value):
            return True, value[index], ""
        return False, None, f"list index `{token}` is out of range"
    return False, None, f"cannot read `{token}` from {type(value).__name__}"


def _token_base(token: str) -> str:
    match = _SELECTOR_RE.match(token)
    return match.group("base") if match else token


def _resolve_selector(value: Any, key: str, expected: str) -> tuple[bool, Any, str]:
    if isinstance(value, dict):
        if key == "id" and expected in value:
            return True, value[expected], ""
        for item_key, item in value.items():
            if isinstance(item, dict) and str(item.get(key, item_key if key == "id" else "")) == expected:
                return True, item, ""
        return False, None, f"selector [{key}={expected}] did not match"
    if isinstance(value, list):
        for item in value:
            if isinstance(item, dict) and str(item.get(key)) == expected:
                return True, item, ""
        return False, None, f"selector [{key}={expected}] did not match"
    return False, None, f"selector [{key}={expected}] cannot be applied to {type(value).__name__}"


def _check_result(
    status: ExpectationStatus,
    expected: dict[str, Any],
    *,
    actual: Any,
    path: str | None,
    op: str | None,
    message: str,
) -> dict[str, Any]:
    return {
        "status": status,
        "message": message,
        "expected": expected,
        "actual": _json_safe(actual),
        "path": path,
        "op": op,
    }


def _aggregate_message(status: ExpectationStatus, checks: list[dict[str, Any]]) -> str:
    if not checks:
        return "No expected checks were provided."
    if status in {"violated", "skipped"}:
        for check in checks:
            if check["status"] == status:
                return str(check["message"])
    return f"All {len(checks)} expected check(s) verified."


def _json_safe(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json", exclude_none=True)
    if isinstance(value, dict):
        return {
            str(key): _json_safe(value[key])
            for key in sorted(value.keys(), key=lambda item: str(item))
        }
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    try:
        json.dumps(value)
    except TypeError:
        return str(value)
    return value


def _limit_value(value: Any, *, max_string: int = 1000, depth: int = 0) -> Any:
    if depth > 8:
        return "<truncated: max depth>"
    if isinstance(value, str):
        if len(value) > max_string:
            return value[: max_string - 3] + "..."
        return value
    if isinstance(value, list):
        return [_limit_value(item, max_string=max_string, depth=depth + 1) for item in value]
    if isinstance(value, dict):
        return {
            str(key): _limit_value(item, max_string=max_string, depth=depth + 1)
            for key, item in value.items()
        }
    return value


def _stable_json_len(value: Any) -> int:
    return len(json.dumps(_json_safe(value), ensure_ascii=False, sort_keys=True))
