"""
json_path_picker.py
-------------------
Click on a value in a pretty-printed JSON Text widget to copy its full
pm.response.json() path to clipboard.

Ctrl+Click on any line in the response body to get the path copied.

Approach: Parse the JSON, pretty-print it ourselves with the same indent,
and build a line-number-to-path map. Then look up the clicked line.
"""

import json
import re
import tkinter as tk
from typing import Dict, List, Any, Optional


def bind_json_path_picker(gui):
    """Bind Ctrl+Click on the response body widget to copy JSON path."""
    gui.txt_resp_body.bind("<Control-Button-1>", lambda e: _on_ctrl_click(gui, e))


def _on_ctrl_click(gui, event):
    """Calculate the JSON path for the clicked line and copy to clipboard."""
    txt = gui.txt_resp_body
    idx = txt.index(f"@{event.x},{event.y}")
    line_num = int(idx.split(".")[0])

    content = txt.get("1.0", "end-1c")

    # Try to parse the response as JSON and build a line→path map
    path = _get_path_for_line(content, line_num)

    if path:
        full_path = f"pm.response.json(){path}"
        gui.clipboard_clear()
        gui.clipboard_append(full_path)

        # Brief flash feedback on the status label
        try:
            original = gui.lbl_status.cget("text")
            gui.lbl_status.config(text=f"\U0001f4cb Copied: {full_path}")
            gui.after(2500, lambda: gui.lbl_status.config(text=original))
        except Exception:
            pass


def _get_path_for_line(content: str, target_line: int) -> str:
    """
    Parse the JSON content, rebuild it with known formatting, and map
    each line to its JSON path. Return the path for the target line.
    """
    try:
        data = json.loads(content)
    except (json.JSONDecodeError, ValueError):
        # Can't parse — fall back to indent-based heuristic
        return _heuristic_path(content, target_line)

    # Build line→path map by walking the JSON structure
    # We need to match lines from the displayed pretty-printed content
    lines = content.split("\n")
    if target_line < 1 or target_line > len(lines):
        return ""

    clicked_line = lines[target_line - 1]

    # Extract the key from the clicked line (if any)
    key_match = re.match(r'^\s*"([^"]+)"\s*:', clicked_line)
    clicked_key = key_match.group(1) if key_match else None

    # Walk the structure using indentation tracking
    # Build a stack of (indent_level, path_segment) as we scan top-down
    path_stack: List[str] = []  # stack of path segments
    indent_stack: List[int] = []  # corresponding indent levels
    array_index_stack: List[int] = []  # current array index at each array level
    in_array_stack: List[bool] = []  # whether current level is an array

    for line_idx, line in enumerate(lines):
        line_no = line_idx + 1
        stripped = line.strip()
        indent = len(line) - len(line.lstrip())

        # Pop stack for closing braces/brackets at or below current indent
        while indent_stack and indent <= indent_stack[-1] and stripped in ("}", "},", "]", "],", "}", "},"):
            indent_stack.pop()
            path_stack.pop()
            if in_array_stack:
                in_array_stack.pop()
            if array_index_stack:
                array_index_stack.pop()
            break

        if stripped in ("}", "},", "]", "],"):
            # Closing — handled above
            if line_no == target_line:
                return _format_path(path_stack)
            continue

        # Check for "key": value patterns
        m = re.match(r'^\s*"([^"]+)"\s*:\s*(.*)', line)
        if m:
            key = m.group(1)
            value_part = m.group(2).rstrip(",").strip()

            if line_no == target_line:
                return _format_path(path_stack + [key])

            # If value opens an object or array, push to stack
            if value_part == "{" or value_part == "[":
                indent_stack.append(indent)
                path_stack.append(key)
                is_arr = (value_part == "[")
                in_array_stack.append(is_arr)
                array_index_stack.append(-1 if is_arr else 0)
            continue

        # Array element start: bare '{' or '[' at a deeper level
        if stripped in ("{", "["):
            # This is an array element if parent is an array
            if in_array_stack and in_array_stack[-1]:
                array_index_stack[-1] += 1
                idx_val = array_index_stack[-1]
                # Push this element
                indent_stack.append(indent)
                path_stack.append(f"[{idx_val}]")
                is_arr = (stripped == "[")
                in_array_stack.append(is_arr)
                array_index_stack.append(-1 if is_arr else 0)
            else:
                indent_stack.append(indent)
                path_stack.append("")
                in_array_stack.append(stripped == "[")
                array_index_stack.append(-1 if stripped == "[" else 0)

            if line_no == target_line:
                return _format_path(path_stack)
            continue

        # Bare values in arrays (primitives)
        if stripped and stripped not in ("}", "},", "]", "],"):
            if in_array_stack and in_array_stack[-1]:
                array_index_stack[-1] += 1
                if line_no == target_line:
                    return _format_path(path_stack + [f"[{array_index_stack[-1]}]"])

            if line_no == target_line:
                return _format_path(path_stack)

    return ""


def _format_path(parts: List[str]) -> str:
    """Format path parts into dot notation with bracket indices."""
    result = ""
    for part in parts:
        if not part:
            continue
        if part.startswith("["):
            result += part
        else:
            result += f".{part}"
    return result


def _heuristic_path(content: str, target_line: int) -> str:
    """
    Fallback: use indentation heuristic when JSON can't be parsed.
    Walks backwards from the target line collecting parent keys.
    """
    lines = content.split("\n")
    if target_line < 1 or target_line > len(lines):
        return ""

    target_idx = target_line - 1
    target_indent = len(lines[target_idx]) - len(lines[target_idx].lstrip())

    parts = []
    key = _extract_key(lines[target_idx])
    if key:
        parts.append(key)

    current_indent = target_indent
    i = target_idx - 1

    while i >= 0:
        line = lines[i]
        indent = len(line) - len(line.lstrip())
        stripped = line.strip()

        if indent < current_indent:
            k = _extract_key(line)
            if k:
                # Check if value is an array
                value_part = re.sub(r'^\s*"[^"]+"\s*:\s*', '', line).strip().rstrip(",")
                if value_part == "[":
                    # Count array index
                    arr_idx = _count_array_index(lines, i, target_idx)
                    parts.append(f"[{arr_idx}]")
                parts.append(k)
                current_indent = indent
            elif stripped in ("{", "["):
                if stripped == "[":
                    arr_idx = _count_array_index(lines, i, target_idx)
                    parts.append(f"[{arr_idx}]")
                current_indent = indent
            i -= 1
            continue
        i -= 1

    parts.reverse()
    return _format_path(parts)


def _extract_key(line: str) -> str:
    m = re.match(r'^\s*"([^"]+)"\s*:', line)
    return m.group(1) if m else ""


def _count_array_index(lines: list, array_line: int, target: int) -> int:
    """Count which array element index contains the target line."""
    array_indent = len(lines[array_line]) - len(lines[array_line].lstrip())
    # Element indent is one level deeper
    elem_indent = None
    index = -1

    for i in range(array_line + 1, target + 1):
        line = lines[i]
        indent = len(line) - len(line.lstrip())
        stripped = line.strip()

        if elem_indent is None and indent > array_indent:
            elem_indent = indent

        if indent == elem_indent and stripped.startswith("{"):
            index += 1
        elif indent == elem_indent and stripped.startswith("["):
            index += 1
        elif indent == elem_indent and not stripped.startswith("}") and not stripped.startswith("]") and stripped:
            index += 1

        if indent <= array_indent and stripped in ("]", "],"):
            break

    return max(0, index)
