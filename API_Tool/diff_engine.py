#!/usr/bin/env python3
"""
diff_engine.py
--------------
Pure JSON diff utilities (stdlib only, no side-effects).

Interface:
    diff_json(a, b) -> {
        "valid": bool,              # True if no differences
        "count": int,               # number of differences
        "lines": List[str],         # human-friendly, path-aware lines
        "stats": dict               # counters (added, removed, changed, type_changed, list_len_changed)
    }

Conventions:
- JSON Pointer-like paths starting at "$" (e.g., $.user.id, $.items[3].sku)
- Dicts: report key added/removed/changed/type-changed
- Lists: strict index-by-index comparison; length mismatches reported
- Scalars: value mismatch or type mismatch
"""

from typing import Any, Dict, List, Tuple

def _type_name(x: Any) -> str:
    if x is None: return "null"
    if isinstance(x, bool): return "boolean"
    if isinstance(x, int) and not isinstance(x, bool): return "integer"
    if isinstance(x, float): return "number"
    if isinstance(x, str): return "string"
    if isinstance(x, list): return "array"
    if isinstance(x, dict): return "object"
    return type(x).__name__

def _path_join(parent: str, key: Any) -> str:
    """Format child path under parent using $.a.b and $.arr[3]"""
    if isinstance(key, int):
        return f"{parent}[{key}]"
    # strings / object keys
    if parent == "$":
        return f"{parent}.{key}"
    return f"{parent}.{key}"

def _diff_dict(a: Dict[str, Any], b: Dict[str, Any], path: str, lines: List[str], stats: Dict[str, int]) -> None:
    a_keys = set(a.keys())
    b_keys = set(b.keys())

    # removed
    for k in sorted(a_keys - b_keys):
        lines.append(f"{_path_join(path, k)}: ❌ removed (was {repr(a[k])})")
        stats["removed"] += 1

    # added
    for k in sorted(b_keys - a_keys):
        lines.append(f"{_path_join(path, k)}: ❌ added (is {repr(b[k])})")
        stats["added"] += 1

    # present in both
    for k in sorted(a_keys & b_keys):
        _diff_any(a[k], b[k], _path_join(path, k), lines, stats)

def _diff_list(a: List[Any], b: List[Any], path: str, lines: List[str], stats: Dict[str, int]) -> None:
    if len(a) != len(b):
        lines.append(f"{path}: ❌ array length changed (expected {len(a)}, actual {len(b)})")
        stats["list_len_changed"] += 1
    # Compare up to the min length
    n = min(len(a), len(b))
    for i in range(n):
        _diff_any(a[i], b[i], _path_join(path, i), lines, stats)

def _diff_any(a: Any, b: Any, path: str, lines: List[str], stats: Dict[str, int]) -> None:
    ta, tb = _type_name(a), _type_name(b)
    if ta != tb:
        lines.append(f"{path}: ❌ type changed (expected {ta}, actual {tb})")
        stats["type_changed"] += 1
        return

    if isinstance(a, dict):
        _diff_dict(a, b, path, lines, stats)
    elif isinstance(a, list):
        _diff_list(a, b, path, lines, stats)
    else:
        # scalar
        if a != b:
            lines.append(f"{path}: ❌ value changed (expected {repr(a)}, actual {repr(b)})")
            stats["changed"] += 1

def diff_json(a: Any, b: Any) -> Dict[str, Any]:
    lines: List[str] = []
    stats: Dict[str, int] = {
        "added": 0,
        "removed": 0,
        "changed": 0,
        "type_changed": 0,
        "list_len_changed": 0
    }
    _diff_any(a, b, "$", lines, stats)
    count = len(lines)
    return {
        "valid": count == 0,
        "count": count,
        "lines": lines,
        "stats": stats,
    }