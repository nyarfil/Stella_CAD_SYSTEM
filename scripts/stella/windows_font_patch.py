"""Re-apply after `uv sync`: skip corrupt Windows fonts that crash build123d import."""
from __future__ import annotations

import sys
from pathlib import Path

NEEDLE = '''        _, ext = os.path.splitext(path)
        if ext.strip(".").lower() == "ttc":  # pragma: no cover
            fonts = ttCollection.TTCollection(path)
        else:
            fonts = [TTFont(path)]
'''
PATCH = '''        _, ext = os.path.splitext(path)
        try:
            if ext.strip(".").lower() == "ttc":  # pragma: no cover
                fonts = ttCollection.TTCollection(path)
            else:
                fonts = [TTFont(path)]
        except Exception:
            return []
'''


def target_path() -> Path:
    repo = Path(__file__).resolve().parents[2]
    return repo / "agentcad-for-windows" / ".venv" / "Lib" / "site-packages" / "build123d" / "text.py"


def main() -> int:
    target = target_path()
    if not target.is_file():
        print(f"missing {target}; run scripts/stella/setup.ps1 first", file=sys.stderr)
        return 1
    text = target.read_text(encoding="utf-8")
    if PATCH in text:
        print("already patched", target)
        return 0
    if NEEDLE not in text:
        print("unexpected build123d text.py; not patched", target, file=sys.stderr)
        return 1
    target.write_text(text.replace(NEEDLE, PATCH, 1), encoding="utf-8")
    print("patched", target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
