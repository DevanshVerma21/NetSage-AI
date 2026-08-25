"""Convert a Pydantic model into the schema dialect Gemini's ``generate_content`` accepts.

Why this exists: ``generation_config.response_schema`` on the stable endpoint is an older
Schema proto that accepts only a subset of JSON Schema. Two Pydantic outputs break it:

* ``additionalProperties`` — emitted by ``ConfigDict(extra="forbid")``. The API rejects the
  field outright with ``Unknown name "additional_properties" ... Cannot find field``.
* ``$defs`` / ``$ref`` — emitted for every nested model. The proto has no general ``$ref``.

Rather than weaken the Pydantic models (strict validation is worth keeping on the parsing
side, and it still catches a provider inventing fields in the JSON-repair path), the wire
schema is derived and sanitised here. Built entirely from public Pydantic API — no reliance
on the SDK's private ``_transformers`` module, so an SDK refactor cannot silently break it.
"""

from __future__ import annotations

import copy
from typing import Any

from pydantic import BaseModel

# Keys the Schema proto understands. Anything else is dropped rather than passed through,
# because the API errors on unknown fields instead of ignoring them.
_ALLOWED_KEYS = frozenset(
    {
        "type",
        "format",
        "title",
        "description",
        "nullable",
        "enum",
        "items",
        "properties",
        "required",
        "minimum",
        "maximum",
        "min_items",
        "max_items",
        "any_of",
        "property_ordering",
    }
)

# JSON Schema spellings that map onto a differently-named proto field.
_RENAMED_KEYS = {
    "minItems": "min_items",
    "maxItems": "max_items",
    "anyOf": "any_of",
}

# The proto uses an upper-case type enum.
_TYPE_MAP = {
    "string": "STRING",
    "number": "NUMBER",
    "integer": "INTEGER",
    "boolean": "BOOLEAN",
    "array": "ARRAY",
    "object": "OBJECT",
    "null": "NULL",
}


def gemini_response_schema(model: type[BaseModel]) -> dict[str, Any]:
    """Return a Gemini-safe response schema for ``model``."""
    raw = model.model_json_schema()
    definitions = raw.pop("$defs", {})
    inlined = _inline_refs(raw, definitions)
    return _sanitise(inlined)


def _inline_refs(node: Any, definitions: dict[str, Any], depth: int = 0) -> Any:
    """Replace every ``$ref`` with a copy of its definition.

    ``depth`` guards against a self-referential model recursing forever; the AI schema is
    only two levels deep, so the limit is generous.
    """
    if depth > 20:  # pragma: no cover - defensive
        raise ValueError("schema nesting is too deep to inline; is the model recursive?")

    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str) and ref.startswith("#/$defs/"):
            name = ref.split("/")[-1]
            if name not in definitions:  # pragma: no cover - defensive
                raise ValueError(f"schema references unknown definition: {name}")
            resolved = copy.deepcopy(definitions[name])
            # Merge any sibling keys (e.g. a description alongside the $ref).
            siblings = {k: v for k, v in node.items() if k != "$ref"}
            resolved.update(siblings)
            return _inline_refs(resolved, definitions, depth + 1)
        return {key: _inline_refs(value, definitions, depth + 1) for key, value in node.items()}

    if isinstance(node, list):
        return [_inline_refs(item, definitions, depth + 1) for item in node]

    return node


def _sanitise(node: Any) -> Any:
    """Drop unsupported keys, rename the renamed ones, and upper-case ``type``."""
    if isinstance(node, list):
        return [_sanitise(item) for item in node]

    if not isinstance(node, dict):
        return node

    result: dict[str, Any] = {}
    for key, value in node.items():
        proto_key = _RENAMED_KEYS.get(key, key)
        if proto_key not in _ALLOWED_KEYS:
            continue

        if proto_key == "type":
            if isinstance(value, list):
                # ["string", "null"] is Pydantic's Optional spelling.
                non_null = [item for item in value if item != "null"]
                mapped = _TYPE_MAP.get(non_null[0] if non_null else "string", "STRING")
                result["type"] = mapped
                if len(non_null) != len(value):
                    result["nullable"] = True
                continue
            result["type"] = _TYPE_MAP.get(value, str(value).upper())
            continue

        if proto_key == "properties" and isinstance(value, dict):
            result["properties"] = {
                name: _sanitise(subschema) for name, subschema in value.items()
            }
            continue

        result[proto_key] = _sanitise(value)

    return result
