"""Project-wide analysis: classify every Java class, count testable methods,
detect which already have a *Test.java companion. Output is a plain dict that
main.py serializes to JSON.

Ported from spring-test-generator's AnalyzeMojo.
"""

from pathlib import Path
from typing import Any, Dict, List

from parser import parse_java_file


def analyze_project(project_root: str) -> Dict[str, Any]:
    root = Path(project_root)
    src_main = root / "src" / "main" / "java"
    src_test = root / "src" / "test" / "java"

    summary: Dict[str, Any] = {
        "project_root": str(root),
        "total_classes": 0,
        "by_stereotype": {},
        "testable_methods": 0,
        "missing_tests": [],
        "classes": [],
    }
    if not src_main.exists():
        summary["error"] = f"src/main/java not found under {root}"
        return summary

    for file_path in src_main.rglob("*.java"):
        try:
            comp = parse_java_file(str(file_path), str(root))
        except Exception as e:
            summary["classes"].append({
                "file": str(file_path),
                "error": str(e),
            })
            continue
        if not comp.name:
            continue
        summary["total_classes"] += 1
        summary["by_stereotype"][comp.stereotype] = summary["by_stereotype"].get(comp.stereotype, 0) + 1
        summary["testable_methods"] += len(comp.methods)

        # Check whether a test file exists for this class
        pkg_path = comp.package.replace(".", "/")
        test_file = src_test / pkg_path / f"{comp.name}Test.java"
        has_test = test_file.exists()
        if not has_test and comp.methods:
            summary["missing_tests"].append({
                "fqn": f"{comp.package}.{comp.name}",
                "stereotype": comp.stereotype,
                "testable_methods": len(comp.methods),
            })

        summary["classes"].append({
            "fqn": f"{comp.package}.{comp.name}",
            "stereotype": comp.stereotype,
            "dependencies": [d.name for d in comp.dependencies],
            "method_count": len(comp.methods),
            "has_test": has_test,
        })

    return summary
