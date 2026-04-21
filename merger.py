"""Merge freshly-generated @Test methods into an existing *Test.java file.

Ported from junit-test-generator's TestFileWriter: read the existing file, detect
already-covered method names, and only splice in new @Test blocks before the final
closing brace. All other structure (imports, fields, helper methods) is preserved.
"""

import re
from pathlib import Path
from typing import List

from indexer import get_parser


_TEST_METHOD_NAME_RE = re.compile(r"\bvoid\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(")


def existing_test_method_names(path: Path) -> List[str]:
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return []
    parser = get_parser()
    tree = parser.parse(bytes(text, "utf-8"))
    names: List[str] = []
    def walk(node):
        if node.type == "method_declaration":
            name_node = node.child_by_field_name("name")
            if name_node:
                names.append(text[name_node.start_byte:name_node.end_byte])
        for c in node.children:
            walk(c)
    walk(tree.root_node)
    return names


def _extract_test_blocks(generated: str) -> List[str]:
    """Split the newly generated file into @Test method source blocks."""
    lines = generated.splitlines()
    blocks: List[str] = []
    current: List[str] = []
    in_block = False
    brace_depth = 0
    for ln in lines:
        stripped = ln.strip()
        if not in_block:
            if stripped.startswith("@Test") or stripped.startswith("@org.junit.jupiter.api.Test"):
                in_block = True
                current = [ln]
                brace_depth = 0
            continue
        current.append(ln)
        brace_depth += ln.count("{") - ln.count("}")
        if brace_depth == 0 and "}" in ln:
            blocks.append("\n".join(current))
            current = []
            in_block = False
    return blocks


def _method_name_of_block(block: str) -> str:
    m = _TEST_METHOD_NAME_RE.search(block)
    return m.group(1) if m else ""


def merge_into_existing(existing_path: Path, generated_code: str) -> str:
    """Return the merged content. Only @Test methods absent from existing are added."""
    existing_text = existing_path.read_text(encoding="utf-8")
    existing_names = set(existing_test_method_names(existing_path))
    new_blocks = _extract_test_blocks(generated_code)
    added: List[str] = []
    for block in new_blocks:
        name = _method_name_of_block(block)
        if not name or name in existing_names:
            continue
        added.append(block)
        existing_names.add(name)
    if not added:
        return existing_text
    last_close = existing_text.rfind("}")
    if last_close == -1:
        return existing_text + "\n" + "\n\n".join(added) + "\n}\n"
    insertion = "\n\n" + "\n\n".join(added) + "\n"
    return existing_text[:last_close] + insertion + existing_text[last_close:]
