"""Install the vendored STEVE add-in into the Fusion AddIns folder (no STEVE installer, no downloads).

  python scripts/install.py --dry-run
  python scripts/install.py                 # refuses if the target exists
  python scripts/install.py --replace       # timestamped backup of the old folder first
  python scripts/install.py --seed-config   # also write the seam config (enabled, fixed port, panel allow-list) and provider.json (claude)

--replace keeps an already fetched Codex `runtime/` folder and the add-in's `stella-seam.json` (moved aside, put back after the copy).

Never writes steve-install-marker.txt, never touches other add-ins, never runs fetch_runtime.py.
"""
import argparse
import hashlib
import json
import os
import shutil
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
SOURCE = HERE / "addin" / "STEVE"
TARGET = Path(os.environ.get("APPDATA", "")) / "Autodesk" / "Autodesk Fusion 360" / "API" / "AddIns" / "STEVE"
DATA_HOME = Path(os.environ.get("LOCALAPPDATA", "")) / "STEVE"
BACKUPS = HERE / "backups"
SEAM_PORT = 47615
PANEL_ALLOWED_DOCUMENTS = ["STELLA_FUSION_SANDBOX"]
KEEP = ("runtime", "stella-seam.json")  # not part of the vendored source; survive --replace
SKIP_DIRS = {"__pycache__", ".git", "tests", ".pytest_cache"}
SKIP_FILES = {"steve-install-marker.txt"}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def files():
    out = []
    for root, dirs, names in os.walk(SOURCE):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
        for name in sorted(names):
            if name in SKIP_FILES or name.endswith(".pyc"):
                continue
            out.append(Path(root, name).relative_to(SOURCE))
    return out


def write_if_absent(path, value, dry):
    if path.exists():
        print("keep existing", path)
    else:
        print("write", path)
        if not dry:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(value), encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--replace", action="store_true")
    ap.add_argument("--seed-config", action="store_true")
    args = ap.parse_args()
    if not os.environ.get("APPDATA") or not SOURCE.is_dir():
        sys.exit("APPDATA or source missing")
    listing = files()
    parked = []
    print("source:", SOURCE, "->", TARGET, "(%d files)" % len(listing))
    if TARGET.exists():
        if not args.replace:
            sys.exit("target exists; pass --replace (a timestamped backup is made first)")
        backup = BACKUPS / ("STEVE-" + time.strftime("%Y%m%d-%H%M%S"))
        print("backup:", TARGET, "->", backup)
        if not args.dry_run:
            for name in KEEP:  # same volume: a rename, not a 300 MB copy
                if (TARGET / name).exists():
                    parked.append((name, TARGET.parent / (".STEVE-keep-" + name)))
                    print("keep", name)
                    (TARGET / name).rename(parked[-1][1])
            BACKUPS.mkdir(parents=True, exist_ok=True)
            shutil.move(str(TARGET), str(backup))
    for rel in listing:
        print("copy", rel.as_posix())
        if not args.dry_run:
            dest = TARGET / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(SOURCE / rel, dest)
    for name, aside in parked:
        aside.rename(TARGET / name)
    if args.seed_config:
        seam = {"enabled": True, "port": SEAM_PORT, "panel": {"allowedDocuments": PANEL_ALLOWED_DOCUMENTS}}
        # The add-in folder is what the Fusion process is known to read; the data-folder copy is kept for older setups.
        write_if_absent(TARGET / "stella-seam.json", seam, args.dry_run)
        write_if_absent(DATA_HOME / "stella-seam" / "config.json", seam, args.dry_run)
        write_if_absent(DATA_HOME / "provider.json", {"provider": "claude", "customProvider": "ollama"}, args.dry_run)
    if not args.dry_run:
        print("manifest sha256:", sha(TARGET / "STEVE.manifest"))
    print("dry run only" if args.dry_run else "done")


if __name__ == "__main__":
    main()
