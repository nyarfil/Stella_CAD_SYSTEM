# build123d-mcp trial (optional Build123d text-to-CAD backend)

Third-party: https://github.com/pzfreo/build123d-mcp, Apache-2.0, pinned `build123d-mcp==0.3.90`
(build123d 0.11.1, OCP 7.9.3.1, mcp 2.3.0; full pins in `requirements.lock.txt`). Python 3.13 venv.
Separate runtime from the native Recipe tools. Not registered in `.mcp.json`: opt in per project.

## Install (venv is git-ignored)
    python -m venv integration\build123d-mcp\.venv
    integration\build123d-mcp\.venv\Scripts\python.exe -m pip install -r integration\build123d-mcp\requirements.lock.txt

## Test
    integration\build123d-mcp\.venv\Scripts\python.exe integration\build123d-mcp\smoke_test.py
Builds a 40x20x10 box with a 6 mm through-hole in a temp workspace, exports STEP, re-imports it and
checks volume (expected 7717.257 mm3). `--list` prints the tool schemas.

## Windows caveat
build123d registers all of C:\Windows\Fonts at import and crashes on a corrupt font
(`mstmc.ttf`, 4096 bytes, on this PC). `winfix/sitecustomize.py` (loaded via PYTHONPATH) skips
unreadable fonts at runtime; no upstream/system file is modified. Drop it if upstream fixes this.

## Opt in
Merge `mcp.snippet.json` into the project's MCP config only after the owner selects Build123d.
Generated STEP must pass `brain_import_step` before use.
