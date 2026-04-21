"""Hash manifest used for `--changed-only` incremental generation.

Stores `{source_path: sha256}` inside `.spring_test_gen_manifest.json` at the project
root. When a later run finds a source whose hash matches, generation is skipped.
"""

import hashlib
import json
from pathlib import Path
from typing import Dict


MANIFEST_FILE = ".spring_test_gen_manifest.json"


def _hash_file(path: Path) -> str:
    try:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return ""


def load_manifest(project_root: str) -> Dict[str, str]:
    path = Path(project_root) / MANIFEST_FILE
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_manifest(project_root: str, manifest: Dict[str, str]) -> None:
    path = Path(project_root) / MANIFEST_FILE
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")


def has_changed(project_root: str, source_path: str, manifest: Dict[str, str]) -> bool:
    key = str(Path(source_path).resolve())
    new_hash = _hash_file(Path(source_path))
    if not new_hash:
        return True
    old_hash = manifest.get(key)
    return old_hash != new_hash


def update_entry(project_root: str, source_path: str, manifest: Dict[str, str]) -> None:
    key = str(Path(source_path).resolve())
    new_hash = _hash_file(Path(source_path))
    if new_hash:
        manifest[key] = new_hash
