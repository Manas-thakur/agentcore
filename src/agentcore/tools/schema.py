"""JSON Schema generation from Python type hints and docstrings.

Supports: primitives, ``None``, ``list[X]``/``tuple``/``set``, ``dict[str, X]``,
``Optional``/``Union`` (``X | Y``), ``Literal``, ``Enum``, dataclasses, ``TypedDict``,
``Annotated[X, "description"]`` and pydantic v2 models (when pydantic is installed).
"""

from __future__ import annotations

import dataclasses
import enum
import inspect
import re
import types
import typing
from collections.abc import Callable
from typing import Any, Literal, Union, get_args, get_origin

_PRIMITIVES: dict[Any, dict[str, Any]] = {
    str: {"type": "string"},
    int: {"type": "integer"},
    float: {"type": "number"},
    bool: {"type": "boolean"},
    bytes: {"type": "string"},
    type(None): {"type": "null"},
    Any: {},
    dict: {"type": "object"},
    list: {"type": "array"},
    tuple: {"type": "array"},
    set: {"type": "array"},
}


def _is_pydantic_model(tp: Any) -> bool:
    return inspect.isclass(tp) and hasattr(tp, "model_json_schema") and hasattr(tp, "model_fields")


def _is_typeddict(tp: Any) -> bool:
    return inspect.isclass(tp) and issubclass(tp, dict) and hasattr(tp, "__annotations__")


def is_optional(tp: Any) -> bool:
    """True if ``tp`` is ``X | None`` / ``Optional[X]``."""
    origin = get_origin(tp)
    if origin is Union or origin is types.UnionType:
        return type(None) in get_args(tp)
    return False


def type_to_schema(tp: Any) -> dict[str, Any]:
    """Convert a Python type annotation to a JSON Schema fragment."""
    if tp is inspect.Parameter.empty:
        return {}
    if tp in _PRIMITIVES:
        return dict(_PRIMITIVES[tp])

    origin = get_origin(tp)
    args = get_args(tp)

    if origin is typing.Annotated:
        schema = type_to_schema(args[0])
        for meta in args[1:]:
            if isinstance(meta, str):
                schema["description"] = meta
        return schema

    if origin is Literal:
        values = list(args)
        schema: dict[str, Any] = {"enum": values}
        kinds = {type(v) for v in values}
        if len(kinds) == 1 and next(iter(kinds)) in _PRIMITIVES:
            schema.update(_PRIMITIVES[next(iter(kinds))])
        return schema

    if origin is Union or origin is types.UnionType:
        non_null = [a for a in args if a is not type(None)]
        if len(non_null) == 1:
            inner = type_to_schema(non_null[0])
            if len(non_null) != len(args):  # Optional[X]
                return {"anyOf": [inner, {"type": "null"}]} if inner else {}
            return inner
        options = [type_to_schema(a) for a in args]
        return {"anyOf": options}

    if origin in (list, set, frozenset, typing.Sequence, typing.Iterable) or origin in (
        _abc("Sequence"),
        _abc("Iterable"),
    ):
        schema = {"type": "array"}
        if args:
            schema["items"] = type_to_schema(args[0])
        return schema

    if origin is tuple:
        schema = {"type": "array"}
        if args and not (len(args) == 2 and args[1] is Ellipsis):
            schema["prefixItems"] = [type_to_schema(a) for a in args]
            schema["minItems"] = schema["maxItems"] = len(args)
        elif args:
            schema["items"] = type_to_schema(args[0])
        return schema

    if origin in (dict, typing.Mapping) or origin is _abc("Mapping"):
        schema = {"type": "object"}
        if len(args) == 2 and args[1] is not Any:
            schema["additionalProperties"] = type_to_schema(args[1])
        return schema

    if inspect.isclass(tp) and issubclass(tp, enum.Enum):
        values = [m.value for m in tp]
        schema = {"enum": values}
        kinds = {type(v) for v in values}
        if len(kinds) == 1 and next(iter(kinds)) in _PRIMITIVES:
            schema.update(_PRIMITIVES[next(iter(kinds))])
        return schema

    if _is_pydantic_model(tp):
        return _inline_refs(tp.model_json_schema())

    if dataclasses.is_dataclass(tp) and inspect.isclass(tp):
        return _dataclass_schema(tp)

    if _is_typeddict(tp):
        hints = typing.get_type_hints(tp)
        required = sorted(getattr(tp, "__required_keys__", hints.keys()))
        return {
            "type": "object",
            "properties": {k: type_to_schema(v) for k, v in hints.items()},
            "required": required,
        }

    # Unknown class: fall back to a string description so the model still gets a hint.
    return {"type": "string", "description": f"{getattr(tp, '__name__', tp)}"}


def _abc(name: str) -> Any:
    import collections.abc as cabc

    return getattr(cabc, name)


def _dataclass_schema(cls: type) -> dict[str, Any]:
    hints = typing.get_type_hints(cls, include_extras=True)
    props: dict[str, Any] = {}
    required: list[str] = []
    doc_params = parse_docstring(cls.__doc__ or "")[1]
    for f in dataclasses.fields(cls):
        schema = type_to_schema(hints.get(f.name, Any))
        if f.name in doc_params:
            schema.setdefault("description", doc_params[f.name])
        has_default = (
            f.default is not dataclasses.MISSING or f.default_factory is not dataclasses.MISSING
        )
        if f.default is not dataclasses.MISSING and _json_safe(f.default):
            schema["default"] = _json_default(f.default)
        if not has_default:
            required.append(f.name)
        props[f.name] = schema
    out: dict[str, Any] = {"type": "object", "properties": props, "required": required}
    if cls.__doc__ and not cls.__doc__.startswith(cls.__name__ + "("):
        out["description"] = parse_docstring(cls.__doc__)[0]
    return out


def _inline_refs(schema: dict[str, Any]) -> dict[str, Any]:
    """Resolve local ``$ref`` pointers so providers that dislike ``$defs`` still work."""
    defs = schema.pop("$defs", {})

    def resolve(node: Any) -> Any:
        if isinstance(node, dict):
            if "$ref" in node and node["$ref"].startswith("#/$defs/"):
                target = defs.get(node["$ref"].split("/")[-1], {})
                return resolve(dict(target))
            return {k: resolve(v) for k, v in node.items()}
        if isinstance(node, list):
            return [resolve(x) for x in node]
        return node

    return resolve(schema)


def _json_safe(value: Any) -> bool:
    return value is None or isinstance(value, (str, int, float, bool, enum.Enum))


def _json_default(value: Any) -> Any:
    return value.value if isinstance(value, enum.Enum) else value


# --- Docstring parsing -----------------------------------------------------------

_SECTION_RE = re.compile(
    r"^\s*(Args|Arguments|Parameters|Params|Returns|Return|Raises|Yields|Examples?|Notes?)\s*:?\s*$"
)


def parse_docstring(doc: str) -> tuple[str, dict[str, str]]:
    """Parse a Google, NumPy or Sphinx style docstring.

    Returns ``(summary, {param_name: description})``.
    """
    doc = inspect.cleandoc(doc or "")
    if not doc:
        return "", {}
    lines = doc.splitlines()
    params: dict[str, str] = {}

    # Sphinx / reST: ":param name: description"
    for m in re.finditer(r":param\s+(?:[^:]+\s)?(\w+):\s*(.+)", doc):
        params[m.group(1)] = m.group(2).strip()

    summary_lines: list[str] = []
    section: str | None = None
    current: str | None = None
    i = 0
    while i < len(lines):
        line = lines[i]
        sec = _SECTION_RE.match(line)
        # NumPy style: "Parameters" followed by a "----------" underline.
        if sec and i + 1 < len(lines) and set(lines[i + 1].strip()) == {"-"}:
            section = sec.group(1).lower()
            i += 2
            continue
        if sec and line.rstrip().endswith(":"):
            section = sec.group(1).lower()
            i += 1
            continue
        if section is None:
            if line.strip().startswith(":"):
                section = "sphinx"
            else:
                summary_lines.append(line)
        elif section in ("args", "arguments", "parameters", "params"):
            google = re.match(r"^\s{0,8}(\*{0,2}\w+)\s*(?:\(([^)]*)\))?\s*:\s*(.*)$", line)
            numpy = re.match(r"^(\w+)\s*:\s*(.*)$", line)
            if google and (line.startswith(" ") or line.startswith("\t")):
                current = google.group(1).lstrip("*")
                params[current] = google.group(3).strip()
            elif numpy and not line.startswith(" "):
                current = numpy.group(1)
                params[current] = ""
            elif current and line.strip():
                params[current] = (params[current] + " " + line.strip()).strip()
            elif not line.strip():
                current = None
        i += 1

    summary = "\n".join(summary_lines).strip()
    # Only the first paragraph is the summary.
    summary = summary.split("\n\n")[0].replace("\n", " ").strip()
    return summary, params


def function_to_schema(
    fn: Callable[..., Any], skip: tuple[str, ...] = ()
) -> tuple[str, dict[str, Any]]:
    """Build ``(description, parameters_schema)`` for a callable."""
    sig = inspect.signature(fn)
    try:
        hints = typing.get_type_hints(fn, include_extras=True)
    except Exception:  # unresolvable forward refs: degrade gracefully
        hints = {}
    summary, doc_params = parse_docstring(fn.__doc__ or "")

    properties: dict[str, Any] = {}
    required: list[str] = []
    for name, param in sig.parameters.items():
        if name in skip or name in ("self", "cls"):
            continue
        if param.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
            continue
        tp = hints.get(name, param.annotation)
        schema = type_to_schema(tp)
        if name in doc_params and doc_params[name]:
            schema["description"] = doc_params[name]
        if param.default is inspect.Parameter.empty:
            required.append(name)
        elif _json_safe(param.default):
            schema["default"] = _json_default(param.default)
        properties[name] = schema

    params_schema: dict[str, Any] = {"type": "object", "properties": properties}
    if required:
        params_schema["required"] = required
    return summary, params_schema
