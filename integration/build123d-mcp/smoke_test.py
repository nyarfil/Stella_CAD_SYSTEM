"""Smoke test: launch build123d-mcp over stdio, build 40x20x10 box with 6mm hole, export STEP.
Usage: .venv/Scripts/python.exe smoke_test.py [--list]"""
import asyncio, json, math, os, sys, tempfile
from pathlib import Path
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = Path(__file__).resolve().parent
EXE = HERE / ".venv" / "Scripts" / "build123d-mcp.exe"
CODE = ("from build123d import *\n"
        "with BuildPart() as p:\n"
        "    Box(40, 20, 10)\n"
        "    Hole(radius=3)\n"
        "result = p.part\n")

async def main():
    work = Path(tempfile.mkdtemp(prefix="b123d_smoke_"))
    env = dict(os.environ)
    if sys.platform == "win32":  # see winfix/sitecustomize.py (corrupt system font workaround)
        env["PYTHONPATH"] = str(HERE / "winfix")
    params = StdioServerParameters(command=str(EXE), args=[], cwd=str(work), env=env)
    async with stdio_client(params) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            tools = (await s.list_tools()).tools
            if "--list" in sys.argv:
                for t in tools: print(t.name, json.dumps(t.input_schema)[:300])
                return
            print("tools:", [t.name for t in tools])
            out = work / "box_hole.step"
            res = await s.call_tool("execute", {"code": CODE})
            print("execute:", res.content[0].text[:300])
            res = await s.call_tool("measure", {})
            print("measure:", res.content[0].text[:400])
            res = await s.call_tool("export", {"format": "step", "filename": str(out)})
            print("export:", res.content[0].text[:300])
    print("workspace:", work)
    # Independent re-import of the exported STEP (same venv, build123d/OCP).
    if sys.platform == "win32":
        sys.path.insert(0, str(HERE / "winfix")); import sitecustomize  # noqa: F401
    from build123d import import_step
    expected = 40 * 20 * 10 - math.pi * 3 ** 2 * 10
    size = out.stat().st_size
    vol = import_step(str(out)).volume
    ok = size > 1000 and abs(vol - expected) / expected < 1e-3
    print(f"step_bytes={size} volume={vol:.3f} expected={expected:.3f} -> {'PASS' if ok else 'FAIL'}")
    sys.exit(0 if ok else 1)

asyncio.run(main())
