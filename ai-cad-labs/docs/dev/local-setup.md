# Local development setup

Everything a contributor needs to build, test, and extend AI-CAD on their own machine.
For what the system is and how it works, start with the [README](../../README.md).

## Core setup

```bash
git clone https://github.com/ai-cad-labs/ai-cad.git   # Windows: add -c core.symlinks=true (or use WSL)
cd ai-cad
uv sync            # Python 3.13+, creates .venv, installs the tool layer
```

Install the system cairo library for the renderer:
`brew install cairo` on macOS,
`apt-get install libcairo2` on Debian/Ubuntu.

Frontend (the read-only run dashboard):

```bash
cd frontend
npm install
npm run dev        # http://localhost:5199 (strictPort)
```

Run the test suites:

```bash
uv run --frozen pytest -q                  # tool layer
cd frontend && npm ci && npx vitest run    # frontend
```

The README quickstart uses the plain command forms;
`--frozen` and `npm ci` are the verification-grade forms
that leave the lockfiles untouched.

No `.env` and no API keys: the `claude` CLI carries its own authentication.

## Configuration

There is no `.env`;
the only knobs are optional environment variables (prefix `CAD_`)
read by the DFMA evaluator.
The authoritative contract is the `tools/dfma_evaluator.py` module docstring;
this table is a convenience copy of the interface:

| Variable | What it does | Default |
|---|---|---|
| `CAD_EVALUATOR_MODEL` | Pins the model the vision/DFMA evaluator calls through the `claude` CLI | unset: the CLI's configured default |
| `CAD_EVALUATOR_TIMEOUT_S` | Timeout for one inner evaluation call, in seconds | `300` |
| `CAD_EVALUATOR_CONCURRENCY` | Concurrency cap for a sweep-mode DFMA pass | `4` (floor `1`) |

The shipped [`.claude/settings.json`](../../.claude/settings.json)
pins a large-context evaluator model.
If your Claude account cannot use the pinned model,
override `CAD_EVALUATOR_MODEL`
(as an environment variable, or by editing the pin in `.claude/settings.json`)
with a model you can use,
or remove the pin to fall back to your CLI's default.

Crash isolation for CadQuery execution is a CLI flag, not an env knob:
pass `--subprocess` to `python -m tools.cadquery_executor`
to run geometry in an isolated child process
that survives native OCCT kernel crashes.

## API reference (tool layer)

The API reference lives in the repo at [`../api/README.md`](../api/README.md).
It is markdown generated from the tool-layer docstrings and committed,
so reading it costs nothing and browsing GitHub is enough.

After changing any tool-layer docstring or public surface, regenerate it:

```bash
uv run --frozen python tests/test_api_docs.py --write
```

The test suite fails until you do.
`tests/test_api_docs.py` renders the docstrings fresh,
compares the result against the committed pages,
and names every page that has gone stale.
Fix the docstring and regenerate; never edit a generated page.

## Local reference clones for agentic development

The `reference/` directory ships five distilled CadQuery documents,
and they are all the system needs at runtime.
For deeper development work
(extending the cookbook, verifying an API surface claim, mining new patterns),
clone the upstream CadQuery ecosystem repos into a sibling folder outside this repo
and tell your coding agent where they live:

```bash
mkdir -p ../cadquery-upstream
cd ../cadquery-upstream
git clone https://github.com/CadQuery/cadquery.git
# ...repeat for the rest of the list below
```

Then point your agent at the folder:
a single line in your agent's project context is enough,
for example "upstream CadQuery sources live in `../cadquery-upstream/`".

The nine repos:

| Repo | Role |
|---|---|
| [CadQuery/cadquery](https://github.com/CadQuery/cadquery) | Core CadQuery library |
| [CadQuery/cadquery-contrib](https://github.com/CadQuery/cadquery-contrib) | Community examples and tutorials |
| [CadQuery/cadquery-plugins](https://github.com/CadQuery/cadquery-plugins) | Extension plugins |
| [bernhard-42/cadquery-massembly](https://github.com/bernhard-42/cadquery-massembly) | Mate-based assembly system |
| [cqparts/cqparts](https://github.com/cqparts/cqparts) | Parametric component framework |
| [CadQuery/awesome-cadquery](https://github.com/CadQuery/awesome-cadquery) | Curated resource directory |
| [CadQuery/cq-cli](https://github.com/CadQuery/cq-cli) | Command-line interface |
| [CadQuery/CQ-editor](https://github.com/CadQuery/CQ-editor) | GUI editor (PyQt) |
| [lypwig/cadquery-server](https://github.com/lypwig/cadquery-server) | Web-based CadQuery IDE |

Track latest `main` on all of them; no commit pins.
These are reference material:
if the distilled docs in `reference/` ever drift from upstream,
the docs get fixed.
