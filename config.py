"""Loader for `.springtest.yml` — user-tunable generation settings per project."""

from pathlib import Path
from typing import Any, Dict, List, Optional

from typecatalog import merge_overrides

DEFAULT_CONFIG: Dict[str, Any] = {
    "junit_version": 5,
    "use_assertj": True,
    "use_testcontainers": False,
    "include_patterns": [],
    "exclude_patterns": [],
    "default_overrides": {},
    "merge_mode": "append",  # append | overwrite
}


def _read_yaml_file(path: Path) -> Optional[Dict[str, Any]]:
    try:
        import yaml
    except Exception:
        try:
            return _minimal_yaml_parse(path.read_text(encoding="utf-8"))
        except Exception:
            return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return None


def _minimal_yaml_parse(text: str) -> Dict[str, Any]:
    """A tiny fallback so users aren't forced to install PyYAML just for a flat config.

    Supports only flat `key: value` lines and bool/int/string scalars. For lists or nested
    maps, tell users to install PyYAML.
    """
    out: Dict[str, Any] = {}
    for ln in text.splitlines():
        s = ln.strip()
        if not s or s.startswith("#") or ":" not in s:
            continue
        k, _, v = s.partition(":")
        v = v.strip().strip('"').strip("'")
        if v.lower() in ("true", "false"):
            out[k.strip()] = v.lower() == "true"
        elif v.isdigit():
            out[k.strip()] = int(v)
        elif v:
            out[k.strip()] = v
    return out


def load_config(project_root: str) -> Dict[str, Any]:
    cfg = dict(DEFAULT_CONFIG)
    path = Path(project_root) / ".springtest.yml"
    if path.exists():
        loaded = _read_yaml_file(path)
        if isinstance(loaded, dict):
            cfg.update(loaded)
    overrides = cfg.get("default_overrides") or {}
    if isinstance(overrides, dict):
        merge_overrides({k: str(v) for k, v in overrides.items()})
    return cfg


def should_include(file_path: str, cfg: Dict[str, Any]) -> bool:
    """Apply include/exclude patterns (simple substring match)."""
    includes = cfg.get("include_patterns") or []
    excludes = cfg.get("exclude_patterns") or []
    path_norm = file_path.replace("\\", "/")
    if includes:
        if not any(pat in path_norm for pat in includes):
            return False
    for pat in excludes:
        if pat in path_norm:
            return False
    return True
