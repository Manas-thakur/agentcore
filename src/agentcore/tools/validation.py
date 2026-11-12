"""A small JSON Schema validator with type coercion, plus conversion into Python types.

LLMs frequently send ``"5"`` where an integer is expected, or omit optional fields. We
coerce what is unambiguous and report everything else as a list of readable errors that
can be fed back to the model.
"""

from __future__ import annotations

import dataclasses
import enum
import inspect
import json
import types
import typing
from typing import Any, Union, get_args, get_origin

from agentcore.tools.errors import ToolValidationError

_TYPE_CHECKS: dict[str, Any] = {
    "string": lambda v: isinstance(v, str),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "boolean": lambda v: isinstance(v, bool),
    "array": lambda v: isinstance(v, (list, tuple)),
    "object": lambda v: isinstance(v, dict),
    "null": lambda v: v is None,
}


def _coerce(value: Any, expected: str) -> tuple[bool, Any]:
    """Try to coerce ``value`` into JSON type ``expected``. Returns (ok, value)."""
    try:
        if expected == "integer":
            if isinstance(value, float) and value.is_integer():
                return True, int(value)
            if isinstance(value, str) and value.strip().lstrip("-").isdigit():
                return True, int(value.strip())
        elif expected == "number":
            if isinstance(value, str):
                return True, float(value.strip())
        elif expected == "boolean":
            if isinstance(value, str) and value.strip().lower() in ("true", "false", "1", "0"):
                return True, value.strip().lower() in ("true", "1")
        elif expected == "string":
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                return True, str(value)
        elif expected in ("array", "object") and isinstance(value, str):
            parsed = json.loads(value)
            if _TYPE_CHECKS[expected](parsed):
                return True, parsed
    except (ValueError, json.JSONDecodeError):
        pass
    return False, value


def validate(value: Any, schema: dict[str, Any], path: str = "$") -> tuple[Any, list[str]]:
    """Validate (and coerce) ``value`` against ``schema``. Returns ``(value, errors)``."""
    errors: list[str] = []
    if not schema:
        return value, errors

    if "anyOf" in schema or "oneOf" in schema:
        options = schema.get("anyOf") or schema.get("oneOf")
        for option in options:
            coerced, errs = validate(value, option, path)
            if not errs:
                return coerced, []
        return value, [f"{path}: value {value!r} does not match any allowed type"]

    if "enum" in schema and value not in schema["enum"]:
        # Try coercing to the enum's type (e.g. "1" -> 1)
        for candidate in schema["enum"]:
            if str(candidate) == str(value):
                return candidate, []
        return value, [f"{path}: {value!r} is not one of {schema['enum']}"]

    expected = schema.get("type")
    if isinstance(expected, list):
        for t in expected:
            coerced, errs = validate(value, {**schema, "type": t}, path)
            if not errs:
                return coerced, []
        return value, [f"{path}: expected one of {expected}, got {type(value).__name__}"]

    if expected:
        check = _TYPE_CHECKS.get(expected)
        if check and not check(value):
            ok, value = _coerce(value, expected)
            if not ok:
                return value, [f"{path}: expected {expected}, got {type(value).__name__}"]

    if expected == "object" and isinstance(value, dict):
        props = schema.get("properties", {})
        out = dict(value)
        for req in schema.get("required", []):
            if req not in value:
                errors.append(f"{path}.{req}: missing required field")
        for key, sub in props.items():
            if key in value:
                out[key], errs = validate(value[key], sub, f"{path}.{key}")
                errors.extend(errs)
        extra_schema = schema.get("additionalProperties")
        if isinstance(extra_schema, dict):
            for key in value:
                if key not in props:
                    out[key], errs = validate(value[key], extra_schema, f"{path}.{key}")
                    errors.extend(errs)
        value = out
    elif expected == "array" and isinstance(value, (list, tuple)):
        items = schema.get("items")
        if items:
            new = []
            for i, item in enumerate(value):
                v, errs = validate(item, items, f"{path}[{i}]")
                new.append(v)
                errors.extend(errs)
            value = new
        else:
            value = list(value)

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            errors.append(f"{path}: {value} < minimum {schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            errors.append(f"{path}: {value} > maximum {schema['maximum']}")
    if isinstance(value, str):
        if "minLength" in schema and len(value) < schema["minLength"]:
            errors.append(f"{path}: shorter than {schema['minLength']}")
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            errors.append(f"{path}: longer than {schema['maxLength']}")
    return value, errors


def validate_arguments(
    args: dict[str, Any], schema: dict[str, Any], strict: bool = False
) -> dict[str, Any]:
    """Validate tool-call arguments. Unknown keys are dropped unless ``strict``."""
    if not isinstance(args, dict):
        raise ToolValidationError(f"arguments must be an object, got {type(args).__name__}")
    props = schema.get("properties", {})
    unknown = [k for k in args if k not in props]
    if unknown and strict:
        raise ToolValidationError(f"unknown arguments: {unknown}")
    cleaned = {k: v for k, v in args.items() if k in props or schema.get("additionalProperties")}
    value, errors = validate(cleaned, {**schema, "type": "object"})
    if errors:
        raise ToolValidationError("invalid arguments: " + "; ".join(errors), errors)
    return value


def convert_to_python(value: Any, tp: Any) -> Any:
    """Convert a validated JSON value into the annotated Python type (dataclass, Enum, ...)."""
    if tp is inspect.Parameter.empty or tp is Any or value is None:
        return value
    origin = get_origin(tp)
    args = get_args(tp)
    if origin is typing.Annotated:
        return convert_to_python(value, args[0])
    if origin is Union or origin is types.UnionType:
        for option in args:
            if option is type(None):
                continue
            try:
                return convert_to_python(value, option)
            except Exception:
                continue
        return value
    if origin in (list, set, frozenset, tuple) and isinstance(value, list):
        if origin is tuple and args and not (len(args) == 2 and args[1] is Ellipsis):
            return tuple(convert_to_python(v, t) for v, t in zip(value, args))
        inner = args[0] if args else Any
        items = [convert_to_python(v, inner) for v in value]
        return origin(items) if origin is not list else items
    if origin is dict and isinstance(value, dict) and len(args) == 2:
        return {k: convert_to_python(v, args[1]) for k, v in value.items()}
    if inspect.isclass(tp):
        if issubclass(tp, enum.Enum):
            return value if isinstance(value, tp) else tp(value)
        if hasattr(tp, "model_validate") and isinstance(value, dict):
            return tp.model_validate(value)
        if dataclasses.is_dataclass(tp) and isinstance(value, dict):
            hints = typing.get_type_hints(tp)
            kwargs = {
                f.name: convert_to_python(value[f.name], hints.get(f.name, Any))
                for f in dataclasses.fields(tp)
                if f.name in value
            }
            return tp(**kwargs)
        if tp is float and isinstance(value, int):
            return float(value)
    return value
