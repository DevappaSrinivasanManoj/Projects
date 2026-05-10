#!/usr/bin/env python3
"""
Validate a JSON payload against a JSON Schema and print human-friendly diffs.

Usage:
    python validate_json.py schema.txt payload.txt

- Both arguments can be .txt or .json files; content must be valid JSON.
- If the 'jsonschema' library is installed, the script uses it for validation and
  formats the errors nicely. If not, it uses a built-in validator that covers
  common JSON Schema features.

Features covered by built-in validator:
- types: "object", "array", "string", "integer", "number", "boolean", "null"
- required properties
- properties + additionalProperties (boolean or schema)
- arrays with "items" (single schema or tuple typing), minItems/maxItems, uniqueItems
- enums and const
- strings: minLength/maxLength, pattern
- numbers: minimum/maximum, exclusiveMinimum/exclusiveMaximum
- composition: oneOf, anyOf, allOf (basic handling with best-branch explanation)
- internal $ref to '#/$defs/...' or '#/definitions/...'
- nullable (OpenAPI-style) translated to allow "null"

Outputs:
- Clear, path-aware error messages (e.g., $.user.id: expected integer, got string)
- Summary of counts at the end

Note: This is not a complete JSON Schema implementation, but aims to be pragmatic and readable.
"""

import argparse
import json
import math
import os
import re
import sys
from typing import Any, Dict, List, Tuple, Optional, Set

# ---------- Utilities ----------

def load_json_file(path: str) -> Any:
    with open(path, "r", encoding="utf-8") as f:
        return json.loads(f.read())

def type_name(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int) and not isinstance(value, bool):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return type(value).__name__

def json_pointer(path_elems: List[str]) -> str:
    """Return a JSON Pointer-like string beginning with $ (easier to read)."""
    return "$" + "".join(f"[{e}]" if isinstance(e, int) or e.isdigit() else f".{e}" for e in map(str, path_elems))

def merge_dicts(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(base)
    out.update(override)
    return out

# ---------- $ref resolution ----------

def resolve_ref(ref: str, root_schema: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Resolve internal $ref like '#/$defs/Address' or '#/definitions/User'.
    Returns the referenced schema dict or None if not found.
    """
    if not ref.startswith("#/"):
        return None  # external refs not supported
    path = ref[2:].split("/")
    cur = root_schema
    for p in path:
        if isinstance(cur, dict) and p in cur:
            cur = cur[p]
        else:
            return None
    return cur if isinstance(cur, dict) else None

def deref_schema(schema: Dict[str, Any], root_schema: Dict[str, Any]) -> Dict[str, Any]:
    """
    If schema has $ref, resolve it and merge sibling keys (informal approach).
    JSON Schema spec treats sibling keywords with $ref carefully; here we
    resolve and overlay for pragmatic validation.
    """
    if not isinstance(schema, dict):
        return schema
    if "$ref" in schema and isinstance(schema["$ref"], str):
        target = resolve_ref(schema["$ref"], root_schema)
        if target is None:
            return schema
        # Merge sibling constraints over the referenced target
        siblings = {k: v for k, v in schema.items() if k != "$ref"}
        merged = merge_dicts(target, siblings)
        return merged
    return schema

# ---------- Validation ----------

class ValidationError:
    def __init__(self, path: List[str], message: str, expected: Optional[str] = None, actual: Optional[str] = None):
        self.path = list(path)
        self.message = message
        self.expected = expected
        self.actual = actual

    def __str__(self):
        loc = json_pointer(self.path)
        parts = [f"{loc}: {self.message}"]
        if self.expected is not None or self.actual is not None:
            parts.append(f"(expected: {self.expected}, actual: {self.actual})")
        return " ".join(parts)

def ensure_type_allowed(value: Any, schema: Dict[str, Any]) -> Tuple[bool, Set[str]]:
    allowed: Set[str] = set()
    t = schema.get("type")
    if t is None:
        return True, allowed
    if isinstance(t, list):
        allowed = set(t)
    else:
        allowed = {t}
    # Handle OpenAPI 'nullable: true' by allowing "null"
    if schema.get("nullable") is True:
        allowed.add("null")
    vtype = type_name(value)
    # Treat integer also as number if schema allows number
    if vtype == "integer" and "number" in allowed:
        return True, allowed
    ok = vtype in allowed
    return ok, allowed

def validate_string(value: str, schema: Dict[str, Any], path: List[str]) -> List[ValidationError]:
    errs: List[ValidationError] = []
    min_len = schema.get("minLength")
    max_len = schema.get("maxLength")
    pattern = schema.get("pattern")
    if isinstance(min_len, int) and len(value) < min_len:
        errs.append(ValidationError(path, f"string shorter than minLength {min_len}", expected=f"len >= {min_len}", actual=str(len(value))))
    if isinstance(max_len, int) and len(value) > max_len:
        errs.append(ValidationError(path, f"string longer than maxLength {max_len}", expected=f"len <= {max_len}", actual=str(len(value))))
    if isinstance(pattern, str):
        try:
            if re.fullmatch(pattern, value) is None:
                errs.append(ValidationError(path, f"string does not match pattern /{pattern}/"))
        except re.error:
            errs.append(ValidationError(path, f"invalid regex pattern in schema: /{pattern}/"))
    # Optional simple format checks
    fmt = schema.get("format")
    if fmt == "email":
        if "@" not in value or value.startswith("@") or value.endswith("@"):
            errs.append(ValidationError(path, "invalid email format"))
    elif fmt == "uuid":
        if re.fullmatch(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}", value) is None:
            errs.append(ValidationError(path, "invalid uuid format"))
    elif fmt == "date-time":
        # RFC3339 is complex; light check for ISO-like datetime
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})", value) is None:
            errs.append(ValidationError(path, "invalid date-time format (RFC3339 expected)"))
    return errs

def validate_number(value: float, schema: Dict[str, Any], path: List[str]) -> List[ValidationError]:
    errs: List[ValidationError] = []
    minimum = schema.get("minimum")
    maximum = schema.get("maximum")
    excl_min = schema.get("exclusiveMinimum")
    excl_max = schema.get("exclusiveMaximum")
    if minimum is not None and value < minimum:
        errs.append(ValidationError(path, f"value < minimum {minimum}", expected=f">= {minimum}", actual=str(value)))
    if maximum is not None and value > maximum:
        errs.append(ValidationError(path, f"value > maximum {maximum}", expected=f"<= {maximum}", actual=str(value)))
    if excl_min is not None and value <= excl_min:
        errs.append(ValidationError(path, f"value <= exclusiveMinimum {excl_min}", expected=f"> {excl_min}", actual=str(value)))
    if excl_max is not None and value >= excl_max:
        errs.append(ValidationError(path, f"value >= exclusiveMaximum {excl_max}", expected=f"< {excl_max}", actual=str(value)))
    return errs

def validate_enum_const(value: Any, schema: Dict[str, Any], path: List[str]) -> List[ValidationError]:
    errs: List[ValidationError] = []
    if "const" in schema and value != schema["const"]:
        errs.append(ValidationError(path, "value does not equal 'const'", expected=json.dumps(schema["const"], ensure_ascii=False), actual=json.dumps(value, ensure_ascii=False)))
    if "enum" in schema and isinstance(schema["enum"], list):
        if value not in schema["enum"]:
            errs.append(ValidationError(path, "value not in enum", expected=json.dumps(schema["enum"], ensure_ascii=False), actual=json.dumps(value, ensure_ascii=False)))
    return errs

def validate_object(obj: Dict[str, Any], schema: Dict[str, Any], path: List[str], root_schema: Dict[str, Any]) -> List[ValidationError]:
    errs: List[ValidationError] = []
    schema = deref_schema(schema, root_schema)
    props = schema.get("properties", {})
    req = schema.get("required", [])
    addl = schema.get("additionalProperties", True)

    # Required properties
    if isinstance(req, list):
        for key in req:
            if key not in obj:
                errs.append(ValidationError(path + [key], "missing required property"))

    # Validate known properties
    for key, subschema in props.items():
        if key in obj:
            sub = deref_schema(subschema, root_schema)
            errs.extend(validate_node(obj[key], sub, path + [key], root_schema))

    # Additional properties
    if isinstance(addl, bool):
        if addl is False:
            for key in obj.keys():
                if key not in props:
                    errs.append(ValidationError(path + [key], "unexpected property (additionalProperties: false)"))
    elif isinstance(addl, dict):
        sub = deref_schema(addl, root_schema)
        for key in obj.keys():
            if key not in props:
                errs.extend(validate_node(obj[key], sub, path + [key], root_schema))

    # minProperties/maxProperties
    minp = schema.get("minProperties")
    maxp = schema.get("maxProperties")
    if isinstance(minp, int) and len(obj) < minp:
        errs.append(ValidationError(path, f"object has fewer than minProperties {minp}", expected=f">= {minp}", actual=str(len(obj))))
    if isinstance(maxp, int) and len(obj) > maxp:
        errs.append(ValidationError(path, f"object has more than maxProperties {maxp}", expected=f"<= {maxp}", actual=str(len(obj))))

    return errs

def validate_array(arr: List[Any], schema: Dict[str, Any], path: List[str], root_schema: Dict[str, Any]) -> List[ValidationError]:
    errs: List[ValidationError] = []
    schema = deref_schema(schema, root_schema)
    items = schema.get("items", None)
    min_items = schema.get("minItems")
    max_items = schema.get("maxItems")
    unique = schema.get("uniqueItems", False)

    if isinstance(min_items, int) and len(arr) < min_items:
        errs.append(ValidationError(path, f"array has fewer than minItems {min_items}", expected=f">= {min_items}", actual=str(len(arr))))
    if isinstance(max_items, int) and len(arr) > max_items:
        errs.append(ValidationError(path, f"array has more than maxItems {max_items}", expected=f"<= {max_items}", actual=str(len(arr))))
    if unique:
        seen = set()
        for i, v in enumerate(arr):
            try:
                key = json.dumps(v, sort_keys=True)
            except TypeError:
                key = str(v)
            if key in seen:
                errs.append(ValidationError(path + [i], "duplicate item (uniqueItems: true)"))
            seen.add(key)

    if isinstance(items, dict):
        sub = deref_schema(items, root_schema)
        for i, v in enumerate(arr):
            errs.extend(validate_node(v, sub, path + [i], root_schema))
    elif isinstance(items, list):
        # Tuple typing: validate each index against its schema
        for i, item_schema in enumerate(items):
            if i < len(arr):
                sub = deref_schema(item_schema, root_schema)
                errs.extend(validate_node(arr[i], sub, path + [i], root_schema))
        # Additional tuple items
        addl_items = schema.get("additionalItems", True)
        if isinstance(addl_items, bool) and addl_items is False and len(arr) > len(items):
            for i in range(len(items), len(arr)):
                errs.append(ValidationError(path + [i], "unexpected array item (additionalItems: false)"))
        elif isinstance(addl_items, dict):
            sub = deref_schema(addl_items, root_schema)
            for i in range(len(items), len(arr)):
                errs.extend(validate_node(arr[i], sub, path + [i], root_schema))

    return errs

def best_branch_errors(value: Any, branches: List[Dict[str, Any]], path: List[str], root_schema: Dict[str, Any]) -> Tuple[int, List[ValidationError]]:
    """Validate value against each branch, return index of best (least errors) and its errors."""
    best_idx = -1
    best_errs: List[ValidationError] = []
    for idx, br in enumerate(branches):
        errs = validate_node(value, deref_schema(br, root_schema), path, root_schema)
        if best_idx == -1 or len(errs) < len(best_errs):
            best_idx = idx
            best_errs = errs
    return best_idx, best_errs

def validate_node(value: Any, schema: Dict[str, Any], path: List[str], root_schema: Dict[str, Any]) -> List[ValidationError]:
    errs: List[ValidationError] = []
    schema = deref_schema(schema, root_schema)

    # Type check
    ok, allowed = ensure_type_allowed(value, schema)
    if not ok:
        errs.append(ValidationError(path, "type mismatch", expected="/".join(sorted(allowed)) or "any", actual=type_name(value)))
        # If type mismatched, we still continue with some checks cautiously.

    # Composition
    if "allOf" in schema and isinstance(schema["allOf"], list):
        for sub in schema["allOf"]:
            errs.extend(validate_node(value, sub, path, root_schema))
    if "anyOf" in schema and isinstance(schema["anyOf"], list):
        branches = [deref_schema(br, root_schema) for br in schema["anyOf"]]
        # Any branch passing (zero errors) is OK
        _, br_errs = best_branch_errors(value, branches, path, root_schema)
        if len(br_errs) == len(validate_node(value, {}, path, root_schema)):  # not meaningful; fallback
            pass
        # If all branches produce errors, report the least-error branch
        all_err_counts = [len(validate_node(value, br, path, root_schema)) for br in branches]
        if all(count > 0 for count in all_err_counts):
            best_idx, best_errs = best_branch_errors(value, branches, path, root_schema)
            errs.append(ValidationError(path, f"does not satisfy anyOf (best match branch #{best_idx} shown)"))
            errs.extend(best_errs)
    if "oneOf" in schema and isinstance(schema["oneOf"], list):
        branches = [deref_schema(br, root_schema) for br in schema["oneOf"]]
        pass_counts = 0
        last_best_idx, last_best_errs = best_branch_errors(value, branches, path, root_schema)
        for br in branches:
            if not validate_node(value, br, path, root_schema):
                pass_counts += 1
        if pass_counts != 1:
            errs.append(ValidationError(path, f"does not satisfy exactly one branch of oneOf (matched {pass_counts})"))
            # Show errors for the best (least failing) branch
            errs.extend(last_best_errs)

    # enum/const
    errs.extend(validate_enum_const(value, schema, path))

    # Type-specific validation
    vtype = type_name(value)
    if vtype == "string":
        errs.extend(validate_string(value, schema, path))
    elif vtype in ("integer", "number"):
        num_value = float(value)
        if math.isnan(num_value) or math.isinf(num_value):
            errs.append(ValidationError(path, "number must be finite"))
        else:
            errs.extend(validate_number(num_value, schema, path))
    elif vtype == "object":
        errs.extend(validate_object(value, schema, path, root_schema))
    elif vtype == "array":
        errs.extend(validate_array(value, schema, path, root_schema))

    return errs

# ---------- jsonschema library (optional) ----------

def try_jsonschema_validate(payload: Any, schema: Dict[str, Any]) -> List[ValidationError]:
    """
    If 'jsonschema' is available, use it for robust validation and translate errors
    into our friendly format.
    """
    try:
        import jsonschema
        from jsonschema import Draft202012Validator
    except Exception:
        return None  # Not available

    errors: List[ValidationError] = []
    # Choose a validator; Draft 2020-12 is the most recent broadly supported
    try:
        validator = Draft202012Validator(schema)
    except Exception:
        # Fallback to auto
        validator = jsonschema.validators.validator_for(schema)(schema)

    for err in sorted(validator.iter_errors(payload), key=lambda e: e.path):
        path_elems = list(err.path)
        msg = err.message
        expected = None
        actual = None
        # Heuristic: derive expected/actual from error context when available
        if err.validator == "type":
            expected = "/".join(err.validator_value) if isinstance(err.validator_value, list) else str(err.validator_value)
            actual = type_name(err.instance)
        elif err.validator in ("minLength", "maxLength", "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum"):
            expected = f"{err.validator}={err.validator_value}"
            actual = json.dumps(err.instance, ensure_ascii=False)
        errors.append(ValidationError(path_elems, msg, expected, actual))
    return errors

# ---------- CLI ----------

def main():
    parser = argparse.ArgumentParser(description="Validate JSON payload against JSON Schema with readable diffs.")
    parser.add_argument("schema_file", help="Path to JSON Schema file (can be .txt or .json with valid JSON content)")
    parser.add_argument("payload_file", help="Path to JSON payload file (can be .txt or .json with valid JSON content)")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON values in messages")
    args = parser.parse_args()

    try:
        schema = load_json_file(args.schema_file)
    except Exception as e:
        print(f"Failed to load schema from '{args.schema_file}': {e}", file=sys.stderr)
        sys.exit(2)
    try:
        payload = load_json_file(args.payload_file)
    except Exception as e:
        print(f"Failed to load payload from '{args.payload_file}': {e}", file=sys.stderr)
        sys.exit(2)

    # Validate using jsonschema if present; else built-in validator
    js_errors = try_jsonschema_validate(payload, schema)
    if js_errors is None:
        errors = validate_node(payload, schema, [], schema)
    else:
        errors = js_errors

    if not errors:
        print("✅ Payload is VALID against the schema.")
        sys.exit(0)
    else:
        print("❌ Payload is INVALID. Differences:")
        for e in errors:
            if args.pretty and e.actual is not None and not isinstance(e.actual, str):
                print(str(e))
            else:
                print(str(e))
        print(f"\nSummary: {len(errors)} issue(s) found.")
        # Non-zero exit code so it can be used in CI/scripts
        sys.exit(1)

if __name__ == "__main__":
    main()