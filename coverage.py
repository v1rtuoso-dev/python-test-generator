"""JaCoCo XML parser for coverage-driven test generation.

Given a `jacoco.xml` report and a line-coverage threshold (percent), produce a
set of `(fqn, method_name)` tuples representing methods whose coverage falls
below the threshold. Downstream code uses this set to restrict generation to
uncovered methods only.
"""

from pathlib import Path
from typing import Set, Tuple
import xml.etree.ElementTree as ET


UncoveredSet = Set[Tuple[str, str]]


def parse_jacoco(report_path: str, threshold_percent: float = 50.0) -> UncoveredSet:
    """Return the set of uncovered `(fqn, method)` pairs below `threshold_percent`.

    The JaCoCo XML schema reports methods under class elements with counters
    of various types (LINE, INSTRUCTION, BRANCH, ...). We use LINE coverage
    (missed / (missed + covered)) as the primary signal.
    """
    path = Path(report_path)
    if not path.exists():
        return set()
    try:
        tree = ET.parse(path)
    except Exception:
        return set()

    root = tree.getroot()
    out: UncoveredSet = set()
    for package in root.iter("package"):
        pkg_name = (package.get("name") or "").replace("/", ".")
        for cls in package.findall("class"):
            cls_name = (cls.get("name") or "").split("/")[-1]
            fqn = f"{pkg_name}.{cls_name}" if pkg_name else cls_name
            for method in cls.findall("method"):
                m_name = method.get("name") or ""
                if not m_name or m_name in ("<init>", "<clinit>"):
                    continue
                missed = 0
                covered = 0
                for counter in method.findall("counter"):
                    if counter.get("type") == "LINE":
                        missed = int(counter.get("missed") or 0)
                        covered = int(counter.get("covered") or 0)
                        break
                total = missed + covered
                if total == 0:
                    out.add((fqn, m_name))
                    continue
                coverage_pct = (covered / total) * 100.0
                if coverage_pct < threshold_percent:
                    out.add((fqn, m_name))
    return out


def is_method_uncovered(uncovered: UncoveredSet, fqn: str, method_name: str) -> bool:
    return (fqn, method_name) in uncovered
