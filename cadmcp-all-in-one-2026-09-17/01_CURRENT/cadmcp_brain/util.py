from __future__ import annotations
import hashlib
import json
import math
import re
from pathlib import Path
from .errors import BrainError


def canonical(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def text_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024*1024), b""):
            h.update(block)
    return h.hexdigest()


def safe_id(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_.-]{0,79}", value):
        raise BrainError("INVALID_ID", "Use an ASCII identifier, not a filesystem path.")
    return value


def safe_path(root: Path, relative: str, *, must_exist=True) -> Path:
    p = Path(relative)
    if p.is_absolute() or ".." in p.parts or "\\" in relative or ":" in relative:
        raise BrainError("UNSAFE_PATH", "Only a workspace-relative path with forward slashes is allowed.")
    target = root / p
    # Reject symlinks at every level, including paths that resolve back inside root.
    current = root
    for part in p.parts:
        current /= part
        if current.is_symlink():
            raise BrainError("UNSAFE_PATH", "Symlinks are not accepted.")
    try:
        target.resolve(strict=must_exist).relative_to(root.resolve())
    except (ValueError, FileNotFoundError, OSError) as exc:
        raise BrainError("UNSAFE_PATH", "The requested path is missing or outside the workspace.") from exc
    return target


def check_unique(items, label):
    ids = [x.id for x in items]
    if len(ids) != len(set(ids)):
        raise BrainError("DUPLICATE_ID", f"Duplicate IDs in {label}.")


def compare(actual, op, target, tolerance=0.0):
    if type(actual) is bool or type(target) is bool:
        return type(actual) is type(target) and op == "eq" and actual == target
    if not isinstance(actual, (int, float)) or not math.isfinite(actual):
        return False
    if op == "eq": return abs(actual-target) <= tolerance
    if op == "le": return actual <= target+tolerance
    if op == "ge": return actual >= target-tolerance
    raise BrainError("BAD_OPERATOR", "Unsupported comparator.")
