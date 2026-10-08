# Stella <-> STEVE Fusion bridge - design

Status: implemented and unit/integration tested against a **fake** `adsk`. Never run against real Fusion. Nothing here is installed into Fusion, no host config is modified, and no existing repo file is changed.

## 1. Scope and owner decisions

- Owner decision: replace the community Fusion MCP (faust-machines/fusion360-mcp-server) with STEVE as the Fusion executor. Scope was widened from "execution layer only" to the **full STEVE add-in** (panel UI, chat layer, providers, updater, docs tool, image tools) with **only RMFG removed** (NOTICE.md lists every removed file and edit).
- STEVE (upstream 17e684e, v0.8.1, MIT) has **no external control hook**. This bridge adds one isolated seam (`stella_seam.py`, opt-in) and a Stella-side stdio MCP server that carries all Stella guards.
- Design principle: Stella-originated calls are guarded by the Stella server; STEVE's own chat panel is **not** guarded by any of it (section 4).

## 2. Data flow

```
 MCP host (Codex / Claude Code / Cursor)
        | stdio JSON-RPC 2.0 (frames on stdout, logs on stderr)
        v
 server/stella_steve_bridge_mcp.py   (Stella side, stdlib only)
   mcp_stdio.McpServer -> gateway.Gateway
        1. read-only / allow-list-empty check        (execute only)
        2. policy.check(code)  static AST policy
        3. POST /v1/inspect  -> active document name + document_id
        4. allow-list check (exact name)
        5. POST /v1/{query|execute}  code + unit helpers, bound to document_id
        6. report pinned.before / pinned.after, audit log (decision + result)
        | HTTP, 127.0.0.1 only, Authorization: Bearer <token>
        v
 Fusion process
   steve/stella_seam.py  (HTTP handler thread: auth, Host/Origin check, validate_call)
        | FusionTools.submit(): queue.put + app.fireCustomEvent
        v
   Fusion MAIN THREAD: FusionTools.drain()
        check_target(): document_id == minted id AND activeDocument is that document (re-check on main thread)
        query   -> run_python() directly (no Undo group)
        execute -> CommandDefinition.execute() -> ExecuteHandler runs script inside the command;
                   failure => args.executeFailed = True => Fusion aborts the transaction (one Undo step)
        <- result dict -> seam (viewport PNG written to disk; only path+size returned)
```

Tool mapping: `stella_fusion_inspect` -> `fusion_inspect_document`, `_query` -> `fusion_query_python`, `_execute` -> `fusion_execute_python` (forced `execution_mode=command`; `application` mode is not exposed), `_viewport` -> `fusion_capture_viewport`, `_api_help` -> `fusion_api_help` (offline: installed `adsk` docstrings), `_health` -> seam only. `stella_fusion_api_help` is a sixth tool beyond the five requested (decision for the owner; it is offline and harmless).

## 3. Guards (Stella-side, all in `server/stella_steve_bridge/`)

| Requirement | Where | Behaviour |
|---|---|---|
| Document allow-list | `gateway._python`, `--allow-document` / `STELLA_FUSION_ALLOWED_DOCUMENTS` | Exact, case-sensitive name match against the active document. Execute needs it. Query/inspect/viewport need it unless `--allow-read-any`. `--allow-read-any` never enables execute. Empty list = no modeling. |
| Read-only | `--read-only` | `stella_fusion_execute` refused before any call. |
| Pinned document | gateway + STEVE `check_target` | Gateway identifies the document, sends `document_id`; STEVE re-checks id and active document **on Fusion's main thread** right before running (and again inside the command's execute event). Result carries `pinned.before/after/unchanged`; a changed document after execution adds a warning. A caller bypassing the gateway is still stopped by the id check (tested). |
| Code policy | `policy.check` | Rejects: imports of socket, ssl, http, urllib, requests, subprocess, ctypes, webbrowser, ftplib, smtplib (+ telnetlib, poplib, imaplib, socketserver, xmlrpc, multiprocessing, importlib, builtins, pty, shutil, winreg, httpx, aiohttp); `os.system/popen/exec*/spawn*/remove/...` incl. aliases and `from os import`; Name use of eval/exec/compile/`__import__`; `open()` for write unless a literal absolute path inside `--scratch-dir` (also io.open, codecs.open, `.write_text/.write_bytes/.unlink`); `activeDocument/activeProduct/activeSelections/activeWorkspace/activeProject/activeFolder/activeHub` (attribute or string constant); `.value.objectType`; dangerous dunders; `sys.modules`; missing `def run`. Query mode additionally rejects attribute stores/deletes and mutating-looking names (`add`, `add*`, `create*`, `delete*`, `remove*`, `import*`, `save*`, `close`, ...). **Defence in depth, NOT a sandbox**: getattr/alias tricks, Fusion API calls that export/save files anywhere (`exportManager`, `saveAs`), and anything a determined author can build are not stopped. Round two added a `document_access` rule rejecting `documents`, `close`, `save`, `saveAs`, `saveCopyAs`, `dataFile`, `data`, `exportManager`, `commandDefinitions`, `activate`, `open` as attributes or string constants (both modes; `io.open`/`codecs.open` and the string `"open"` excepted). Known false positives: `file.close()`, a dict key named `"data"` - rename in the script. `app.data` itself is still reachable via string concatenation tricks (static check is bypassable); see the open-document check below. The boundaries that matter are the token, the allow-list, and reviewing code. |
| Units | `policy.with_unit_helpers` | `to_cm(mm)`, `to_mm(cm)` are appended after the user's code (line numbers unchanged) so they are globals inside `run()`. They reject non-numbers, bool, NaN, inf. No other conversion exists; results include a units note. |
| Timeouts | seam `_timeout_seconds` (1..120, default 60) | Bridge wait limit; on expiry the job is flagged cancelled (skipped if not started; a running script cannot be interrupted). STEVE's own 15 s Python trace budget and 12 000 char print cap stay. |
| Size caps | seam 256 KB body/response, client 512 KB, gateway 100 000 chars, STEVE 24 000-char result with truncation metadata | Oversize results become structured errors/previews. |
| Audit | `audit.py`, `<home>/audit.jsonl` | One line per decision (allow/deny + reason) and one per result (code text truncated at 20 000 chars with `code_truncated`/`code_chars`; sha256 covers the full text; rotated at 5 MB, keeping `.1`-`.3`): UTC time, tool, document {name,id}, `code` text, `code_sha256`, status, error_code, duration. The token is never written. |
| No egress from our code | `client.py` | Only `http.client` to `127.0.0.1` (constructor refuses other hosts). No telemetry/updater/search in Stella-authored code. |
| Open-document check | `gateway._open_documents` (trusted Stella query) | Execute snapshots every open document (name, saved, modified) before and after; if it cannot read the list it refuses (`denied_document_snapshot_failed`, fail closed). Any difference other than the pinned document's own flags returns `ok=false`, `policy_violation_other_documents_changed`, with `open_documents{before,after,changed}` and an audit `violation` line. Detects, does not prevent. |
| Data Panel | seam `run_script` wrapper | `context['data']` is set to None for Stella jobs only. STEVE chat is unaffected. |
| Outcome unknown | gateway | A 504 or connection loss during execute returns `outcome_unknown` (inspect before retrying; no other route). |
| No fallback | `gateway.handle` | A failure returns `bridge_unavailable` / the STEVE error with "No other route was tried". Nothing retries via another CAD or Fusion route. |

Seam hardening (`stella_seam.py`): binds `127.0.0.1` only (reuses STEVE's `LoopbackHTTPServer`), constant-time bearer compare, rejects any request with an `Origin` header (browser CSRF) and any `Host` other than `127.0.0.1:port`/`localhost:port` (DNS rebinding), 256 KB body cap, never logs request lines, token file created empty, restricted to the current user (Windows protected DACL via `SetNamedSecurityInfoW`; POSIX chmod 600) and only then filled; never logged. The server binds exclusively (`SO_EXCLUSIVEADDRUSE` on Windows, no address reuse). `endpoint.json` is removed on stop, a failed start tears the server down, and the `STEVE.py` hook is wrapped in try/except through `safe_start` so a seam failure never aborts `run()` (errors go to stderr and `seam-error.log`).

## 4. Trust boundaries

1. MCP host -> Stella server: stdio, trusted parent process.
2. Stella server -> seam: loopback + bearer token. **Whoever holds the token (any process of the same Windows user that can read `<STEVE data>/stella-seam/token`) can submit arbitrary Python straight to the seam, bypassing allow-list, read-only and code policy**, because those live in the Stella server. The token file is restricted to the owner (see section 3), but any process running as that user can still read it. Residual risk.
3. **STEVE's own chat panel is NOT covered by any Stella guard.** The vendored add-in still lets its model (ChatGPT/Grok/Claude/OpenRouter/Ollama) run unrestricted Python in Fusion with the user's privileges, with STEVE's advisory AST guards only (`python_runner.py` docstring: "in-process execution, not a sandbox"). The allow-list, read-only mode, code policy and audit log apply only to calls that come through the Stella MCP server.
4. Seam and STEVE chat share one `FusionTools` queue and one `document_id` registry. If a STEVE chat task has pinned a document, calls for another document fail with `document_changed`; this fails closed.
5. Prompt injection: document names, STEVE docs-tool pages and model output are untrusted. The Stella server never executes anything it did not receive from the MCP host.

## 5. Static review of vendored code (done before any test ran)

Method: AST scan of every `.py` (50 files incl. `claude_native/`) for import-time statements and risky imports, grep for eval/exec/pickle/marshal/`__import__`/`shell=True`, URL-literal scan of all `.py`/`.js`/`.html`.

- **Import-time side effects: none of concern.** Module-level non-def statements are only: `re.compile`, `Path(__file__)`, `threading.Lock/Event` creation, `json.loads` of the add-in's own `STEVE.manifest` (`version.py`), and `TOOLS = list(...)`. Importing `fusion_tools`, `tool_protocol`, `controller`-free modules does nothing else. (Tests import `steve.fusion_tools` and `steve.stella_seam` only, with a fake `adsk`.)
- **No obfuscation, no eval/exec of strings, no pickle/marshal, no `shell=True`, no `os.system`.** The one `exec` is the intended script runner (`python_runner.py:144`) on AST-parsed, compiled user code. `importlib.import_module` is used only for `adsk.*` namespaces (`fusion_tools.py`) after namespace checks.
- **subprocess** (all argument lists, none with `shell=True`): Codex runtime (`transport.py:166`), taskkill (`transport.py:114`, `claude_native/directsdk.py:278`), update installer (`app_update.py:169`), Claude CLI (`claude_native/directsdk.py:261`, `claude_setup.py:56,88,123`), clipboard PowerShell reader (`clipboard.py:93`, embedded script), file opener (`controller.py:53`).
- **ctypes**: Windows DPAPI / macOS Keychain secrets (`secure_store.py`, `grok_auth.py`), `downloads.py`.
- **Network modules**: see the egress table (section 7). Panel JS contains no `fetch`/XHR/WebSocket (only an Ollama placeholder address).
- RMFG: removed, `grep -ri rmfg addin/` is empty; `api.rmfg.com` no longer appears.
- Not reviewed in depth: panel JS beyond grep, `claude_native/*` internals, `update_helper.py`, upstream installer (not vendored).

## 6. Tests

`python -I -m pytest tests` (129 tests; pure stdlib + pytest; fake `adsk` in `tests/fake_adsk/`; only loopback sockets):
- `test_policy.py`: every banned construct, open() write rules, live getters, query-mode mutation heuristics, mm/cm helpers and their input validation.
- `test_bridge_e2e.py`: real `stella_seam` + real vendored `FusionTools` + real `run_python` against the fake Fusion: allow/deny (exact name, case), read-only, no-allow-list, `--allow-read-any` limits, token/Origin/Host checks, 404, body cap, STEVE `validate_call` rejection, application mode refused, **stale/switched `document_id` rejected on the main thread**, failure sets `executeFailed` (rollback flag, `transactionAborted`), mm/cm in a script, seam timeout -> cancelled, result truncation + render cap, viewport returns path+size only, offline api_help + path validation, audit content (code, sha256, decisions), `bridge_unavailable` with no fallback.
- `test_review_fixes.py`: `document_access` rule (attributes and strings, both modes), `data` stripping, open-document before/after violation, snapshot failure, denial messages with the real name, `outcome_unknown`, audit truncation/rotation, `endpoint.json` cleanup, `safe_start`, exclusive bind, hook try/except, token ACL.
- `test_stdio_mcp.py`: spawns the server with `python -I` and drives it as a generic MCP client: initialize (version negotiation for 2024-11-05, 2025-03-26, 2025-06-18, unknown) -> notifications/initialized -> tools/list -> tools/call, `isError` semantics, -32601/-32602/-32700, stdout contains only JSON-RPC frames.

## 7. Outbound network destinations remaining in the full install (after RMFG removal)

Source: URL-literal scan + import audit of the vendored tree. "Stella seam" is inbound loopback only.

| Destination | Where in code | When | Notes |
|---|---|---|---|
| OpenAI / ChatGPT (via the **Codex app-server binary**, which is not in this tree) | `transport.py` (launch `:101`, `:166`); `controller.py:81` `web_search: "live"` | Default provider `chatgpt` (`preferences.py:10`) whenever the chat is used | Binary talks to OpenAI itself; live web search queries leave the machine. |
| `auth.x.ai`, `api.x.ai/v1` (xAI Grok) | `grok_auth.py:19-20`, `grok_transport.py` | provider `grok`; OAuth uses loopback listener | |
| `openrouter.ai` | `openrouter_auth.py:18`, `openrouter_transport.py` | provider `openrouter` | |
| `api.anthropic.com` (via the `claude` CLI / Agent SDK) | `claude_native/directsdk.py:458`, `claude_setup.py` | provider `claude` | Spawns the user's installed `claude` CLI. |
| Ollama `127.0.0.1:11434` or user-set URL; custom OpenAI-compatible server | `ollama_transport.py:12`, `custom_server.py`, `openai_compat_transport.py` | provider `ollama` / `openai` | Destination chosen by the user. |
| `help.autodesk.com` (Fusion API reference) | `documentation.py:10`, tools `fusion_search_docs` / `fusion_fetch_docs` | when the model calls the docs tools | Allow-listed to Autodesk help URLs. |
| `api.github.com/repos/10-X-eng/STEVE/releases`; release zips from github.com | `updates.py:10-13,54`, `downloads.py` | version check at start and every 12 h (`updates.py:13`); download only when "managed" install (`controller.py:270-277`) or user action | See section 9. |
| `api.github.com/repos/openai/codex/releases/latest`; Codex package downloads | `runtime_updates.py:15-16,48,136` | check at start; download on user action | |
| Browser links only (opened in the user's browser, not fetched) | `controller.py:60,754,755,758`: github.com/10-X-eng/STEVE, learn.chatgpt.com, ollama.com | user clicks | |
| ~~api.rmfg.com~~ | removed | - | |

Local-only listeners: STEVE's per-provider "Responses" gateways and OAuth callbacks on `127.0.0.1` ephemeral ports (`claude_responses.py`, `grok_transport.py`, `openrouter_*`), and the Stella seam. No telemetry/analytics endpoint exists in STEVE. Debug logging (`debug_log.py`) writes locally only.

## 8. What is NOT verified (live Fusion behaviour)

Everything above is verified only against a hand-written fake `adsk`. Unproven on a real Fusion:
- `fireCustomEvent` from the seam's HTTP handler thread and main-thread dispatch (STEVE does the same from its transport thread, so likely fine).
- Undo grouping: that `executeFailed = True` really aborts and rolls back the whole script as one step, and that one successful script is exactly one Undo entry. The fake only records the flag.
- Behaviour when STEVE's chat has an active task (pinned document, queued waits) and when a user command is active (`active_command` / queue waits; the seam times out after `_timeout_seconds`).
- `fusion_capture_viewport` (camera restore, isolation, PNG output) and `fusion_inspect_document` on real designs; bounded result sizes on large models.
- That STEVE loads with the seam hook in the Fusion's embedded Python (relative import `from .steve.stella_seam import ...` inside `STEVE.py`).
- Windows ACL on the token file; `explorer`/AV interactions; Fusion minimum version (not stated by upstream).
- The model-driven features of STEVE itself (needs the Codex runtime, not fetched here).
- CAM crash guard, Electronics, DFM paths: untouched upstream code, not exercised.

## 9. Owner-decision settings (upstream defaults, NOT changed)

Paths relative to `addin/STEVE/`.

| Setting | Upstream default | Where | Option if you want it off |
|---|---|---|---|
| Auto-updater (STEVE) | Version check at start and every 12 h (GET api.github.com). Auto-download/install only if the install is "managed", i.e. folder named `STEVE` containing `steve-install-marker.txt` with the exact marker text. This vendored tree has **no marker**, so no auto-download/install, but the check still runs and the panel shows "update available". | `steve/updates.py:10-13,54`; `controller.py:228-230,270-277,313-315`; `STEVE.py:288` (`start_update_checks`); `steve/update_transaction.py:13-18` (`managed`); `steve/app_update.py:99-102` | Never create `steve-install-marker.txt`; to remove the check, make `start_update_checks` a no-op and drop `STEVE.py:288`. |
| Codex runtime updater | Check at start; download only on user action | `steve/runtime_updates.py:15-16`; `controller.py:230,313-315` | same hook |
| Codex `web_search` | `"live"` | `controller.py:81` | set to `"disabled"`/`"cached"` in `thread_config` |
| Provider | `chatgpt` (Codex) | `steve/preferences.py:10`; choices `:26` | choose in panel settings; `ollama` keeps everything local |
| Debug logging | Off (writes code/args/results locally when on) | `steve/debug_log.py:39` (`enabled=False` unless `debug.json`) | leave off |
| Docs tool | On (help.autodesk.com) | `tool_protocol.py` (`fusion_search_docs`, `fusion_fetch_docs`), `documentation.py` | remove the two TOOLS entries |
| DFM switch | Off | `steve/dfm.py` `DfmStore.enabled` | - |
| Stella seam | **Off** until `stella-seam/config.json` has `{"enabled": true}` | `steve/stella_seam.py` | opt-in on purpose |

## 10. Host configuration snippets (READY TO PASTE, NOT APPLIED)

The server is plain stdio MCP (JSON-RPC 2.0, version negotiation, `tools/list`, `tools/call`, `isError` results, no host-specific extensions, logs on stderr). The same command works unchanged from all three hosts. It needs only a Python 3.9+ on PATH (stdlib only; tested on 3.13). Use an absolute interpreter path if `python` on PATH is not the one you want.

Arguments: `--allow-document NAME` (repeatable, exact name), `--read-only`, `--allow-read-any`, `--port N` (default: read `endpoint.json` written by the add-in), `--token-file PATH` (default `%LOCALAPPDATA%/STEVE/stella-seam/token`), `--home DIR`, `--audit-log FILE`, `--scratch-dir DIR`. Env alternative: `STELLA_FUSION_ALLOWED_DOCUMENTS='["Doc A","Doc B"]'`.

**Codex** - `.codex/config.toml`:
```toml
[mcp_servers.stella-fusion-steve]
command = "python"
args = [
  "E:/aiwork/Stella_CAD_SYSTEM/integration/steve-bridge/server/stella_steve_bridge_mcp.py",
  "--allow-document", "STELLA_FUSION_SANDBOX",
  # "--read-only",
  # "--token-file", "C:/Users/nikis/AppData/Local/STEVE/stella-seam/token",
]
startup_timeout_sec = 20
tool_timeout_sec = 130
```
TOML pitfall: forward slashes are fine; with backslashes use single-quoted literal strings (`'C:\Users\...'`), never double-quoted.

**Claude Code** - project `.mcp.json`:
```json
{
  "mcpServers": {
    "stella-fusion-steve": {
      "command": "python",
      "args": [
        "E:/aiwork/Stella_CAD_SYSTEM/integration/steve-bridge/server/stella_steve_bridge_mcp.py",
        "--allow-document", "STELLA_FUSION_SANDBOX"
      ]
    }
  }
}
```
or one command: `claude mcp add stella-fusion-steve --scope project -- python E:/aiwork/Stella_CAD_SYSTEM/integration/steve-bridge/server/stella_steve_bridge_mcp.py --allow-document STELLA_FUSION_SANDBOX`
Pitfalls: everything after `--` belongs to the server (put `claude mcp add` flags before it); a document name containing spaces must be quoted for the shell AND stays one argv element (in PowerShell use `'--allow-document'  'My Doc'`; in JSON no extra quoting). Claude Code asks for approval of project-scoped servers on first use.

**Cursor** - `.cursor/mcp.json` (project) or `~/.cursor/mcp.json`:
```json
{
  "mcpServers": {
    "stella-fusion-steve": {
      "command": "python",
      "args": [
        "E:/aiwork/Stella_CAD_SYSTEM/integration/steve-bridge/server/stella_steve_bridge_mcp.py",
        "--allow-document", "STELLA_FUSION_SANDBOX"
      ]
    }
  }
}
```
Pitfalls: JSON needs doubled backslashes if you do not use forward slashes; Cursor's `${workspaceFolder}` may be used for paths if the project root is the repo; if the document name has spaces or non-ASCII characters prefer `"env": {"STELLA_FUSION_ALLOWED_DOCUMENTS": "[\"My Doc\"]"}`.

Follow-up (not done): Codex and Cursor have skills/agent entries (`.agents/skills/cadmcp-design-brain/SKILL.md`, `.cursor/skills/cadmcp-cursor/SKILL.md`); **an equivalent Claude Code skill/entry does not exist yet** and should be added when this becomes the default route. This task did not write into `.agents/` or `.cursor/`.

## 11. Manual live-test checklist (disposable Fusion document; NOT run)

0. Prerequisites: save and close every other Fusion document first (the open-document check compares the whole list); disable any other STEVE install; save the sandbox in a scratch project. Take the exact name from the denial message (`Active document 'X' is not on the allow-list`) and put it in `--allow-document`; do NOT use `--allow-read-any` as a workaround. An unsaved document is named `Untitled`; a saved one may carry a version suffix (`name v3`) - unverified. A throwaway Fusion document named exactly `STELLA_FUSION_SANDBOX`. Obtain the Codex runtime ONLY if you want STEVE's chat: from an upstream checkout of 10-X-eng/STEVE at 17e684e run `python scripts/fetch_runtime.py` (downloads a SHA-256-pinned Codex 0.155.1 package into `addin/STEVE/runtime/`), or place a verified runtime under `%LOCALAPPDATA%\STEVE\runtimes\` (`transport.py:49-64`). The seam and Stella tools do **not** need it. No Claude/Codex binary was downloaded in this work.
1. Create `%LOCALAPPDATA%\STEVE\stella-seam\config.json` = `{"enabled": true}` (optionally `"port": 17654`).
2. Fusion: Shift+S -> Add-Ins -> green `+` -> choose folder `...\integration\steve-bridge\addin\STEVE` -> Run. (Do not enable Run on Startup yet.) Stop other Fusion MCP add-ins first.
3. Confirm `%LOCALAPPDATA%\STEVE\stella-seam\endpoint.json` and `token` exist. `stella_fusion_health` -> ok.
4. With another document active: `stella_fusion_inspect` must be refused; `stella_fusion_execute` refused.
5. With the sandbox active: `stella_fusion_inspect` -> name and `document_id`.
6. `stella_fusion_query` returning `[b.name for b in context['root'].bRepBodies]` -> works; a query containing `.add(` is rejected by policy.
7. `stella_fusion_execute` creating a 20 x 10 x 5 mm box using `to_cm(...)` -> one entry in Fusion's Undo history; verify the size with a query (cm vs mm!).
8. Execute a script that creates a sketch then raises -> confirm **nothing** remains (rollback) and `transactionAborted` is true.
9. Switch tabs during a pending call; confirm `document_changed` and no edit on the other document.
10. `stella_fusion_viewport` -> PNG path under `...\stella-seam\captures\`; open it.
11. Restart the add-in (Stop/Run) twice; confirm no duplicate command/event errors and the port is released.
12. Read `audit.jsonl`: decisions, code, sha256 present; no token anywhere.
13. Optional: open the STEVE panel, confirm RMFG UI is gone and the Manufacturing row renders.

## 12. Follow-ups

- Claude Code skill/entry equivalent to the Codex/Cursor ones (see section 10).
- Live verification of section 8.
- Decide the section 9 settings (updater, web search, provider) before enabling Run on Startup.
- Optional hardening: restrict the token file ACL with `icacls` (needs a subprocess; deliberately not added to the add-in).

## 13. Default-route migration plan (not applied)

Goal: `stella_fusion_*` (this bridge) becomes the default Fusion route, replacing both the official `fusion` MCP and `stella-fusion-community`. **Nothing below has been changed.** Line numbers were read on 2026-10-08 (read-only inspection; spot-verified). Rule to preserve everywhere: the owner's explicit backend choice only, and **no automatic fallback** to another CAD or another Fusion route on failure.

Capability gap to settle first: the current default (official `fusion` MCP, `C:/Users/nikis/.codex/user-extensions/PREFERENCES.md:5`) is documented for document read/open/close/save/model operations/export. The bridge has no document open/close/save tools (STEVE's `application` execution mode is deliberately not exposed). Decide whether those stay a manual user step or get an explicit, allow-listed tool before dropping the official route.

| # | File : line | Change | Risk |
|---|---|---|---|
| 1 | `C:/Users/nikis/.codex/user-extensions/PREFERENCES.md:5` ("Codex default 2026-10-04 ... official `fusion` MCP is the basic route") | Rewrite the default to the steve-bridge tools; keep the date-stamped history line. Needs the owner's explicit sign-off (it records a prior owner decision). | high (policy) |
| 2 | `C:/Users/nikis/.codex/user-extensions/references/fusion.md:3-5` | Same rewrite; community route becomes legacy/removed. | high (policy) |
| 3 | `AGENTS.md:32` (ClassCAD / community Fusion MCP bullet) and the "FusionのZA13, shared cad-session, existing allowed-document guard" sentence at `AGENTS.md:23` | Line 32: name `stella_fusion_*` as the Fusion route. Line 23: keep verbatim (ZA13, shared cad-session, document guard must not be altered). | low / high-if-lost |
| 4 | `docs/CLASSCAD_FUSION_INTEGRATION_JA.md:20,22,24,26,57` | Replace the community-add-in setup and `--allow-document` instructions with steve-bridge setup (README_STELLA_JA.md); keep the exact-name allow-list explanation. | med |
| 5 | `cadmcp-all-in-one-2026-09-17/01_CURRENT/cadmcp_brain/studio/backend_routing.py:30` (`WORKFLOWS['fusion']` label "stella-fusion-community: project document allowlist, export STEP") | Relabel to the steve-bridge tools. The label carries no tool names; routing is by backend key. | low |
| 6 | same file `:16-17` (`Backend` Literal / `BACKENDS` contain `'fusion'`), `:51` (default `allowed_backends` excludes `fusion`), `:81-82` (`fusion` is last in `order`) | Keep key `'fusion'` (renaming ripples into stored project settings and tests). The default allow-list deliberately excludes `fusion`, so "default Fusion tool" = default *implementation* of the `fusion` key, not auto-selection. Do not add `fusion` to `allowed_backends` defaults unless the owner wants Fusion chosen automatically. | med |
| 7 | same file `:121` (`selected = next(c ... if c['eligible'])`) and `:144` (`'automatic_failure_fallback': False`) | Not a failure fallback (eligibility pick at plan time). Keep `:144` as is and re-run the tests that assert it; never make `fusion` eligible as a fallback target. | low |
| 8 | `.../studio/fusion.py:3-4,243-244` (handoff text "cadMCP cannot call Fusion MCP ... pass script verbatim to `fusion_mcp_execute`", `'fusion_mcp': {...}`) | Hard-wired to the official MCP's tool name. Add a steve-bridge handoff variant (`stella_fusion_execute` with `title` + `code`, unit helpers `to_cm/to_mm`) selected by the explicit choice, keep the official one as an explicit option or remove it by owner decision. | med |
| 9 | `.codex/config.toml:34-39` (`[mcp_servers.stella-fusion-community]`, `--allow-document STELLA_FUSION_COMMUNITY_SANDBOX`) | Add `[mcp_servers.stella-fusion-steve]` (snippet in section 10). Remove the community entry only after live verification. | med |
| 10 | `C:/Users/nikis/.codex/config.toml:101-102` (`[mcp_servers.fusion]` url `http://127.0.0.1:27182/mcp`) and `:104-106` (community) | Add the steve-bridge entry; official entry kept as an explicit choice or removed by owner decision. This is a user-level file: change only with the owner's approval. | med |
| 11 | `integration/fusion-community/` (whole dir; `README_STELLA_JA.md`, `stella_fusion_mcp.py:149-163,189-214,242`, `probe_*.py`, `PINNED_SOURCE.json`) | Do not delete at migration time. Mark as legacy in README; port its **fail-closed allow-list semantics** (done in `gateway.py`) and keep the dir until the live checklist passes. | high if the guard is dropped |
| 12 | `.agents/skills/cadmcp-design-brain/SKILL.md:33`, `README.md:25`; Cursor skill `.cursor/skills/cadmcp-cursor/SKILL.md` | Update the Fusion routing text. Add a Claude Code skill/entry (does not exist yet). | low |
| 13 | `docs/FREECAD_INTEGRATION_JA.md:16` (`.cursor/cad-session.json` is not overwritten) and shared cad-session handling | Preserve unchanged: the bridge never reads or writes cad-session files. | high if broken |
| 14 | `integration/freecad/select_backend.py:28,32,42-43,48` (`SUPPORTED_BACKENDS` has `fusion`; `"fusion": "stella-fusion-community"` backend->server map; managed-server set; per-backend set `{stella-fusion-community, fusion}`) | This is the code that writes the Codex MCP config when the owner selects a backend. Point the `fusion` backend at `stella-fusion-steve`, add it to the managed set, decide whether the old two names are removed, kept or only disabled-on-switch. Keep: selection is explicit, no auto switch on failure. | high (writes config) |

Tests that reference the community/official Fusion route (update or re-run when the configs change):
- `integration/freecad/tests/test_select_backend.py:123-124,136-137` (assert community and official `fusion` are disabled in the relevant configs; will fail if the new `stella-fusion-steve` entry or the official-entry removal changes what is asserted).
- `integration/freecad/tests/test_select_backend.py:91-93,166,175,315` (select_backend(..., "fusion") expectations: server names).
- `integration/freecad/tests/test_route_backend.py:77,85` (allow-list cases for `fusion`).
- `cadmcp-all-in-one-2026-09-17/01_CURRENT/tests/test_fusion_handoff.py:84,109` and `test_studio.py:392` (official `fusion_mcp_execute` handoff; keep or move with item 8).
- Guard tests that must keep passing: this dir's `tests/test_bridge_e2e.py` (`test_bridge_unavailable_has_no_fallback`, allow-list, read-only, pinned-document tests); the community tests under `integration/fusion-community/tests/` stay valid while that dir exists.
- Not confirmed by the read-only scan: enclosing test names for `test_select_backend.py:123`; a repo-wide test search was partial - run `rg -n "fusion-community|stella-fusion-community|fusion_mcp" --glob "*test*"` before editing.

Order of operations (when approved): pass the live checklist (section 11) -> add the config entries -> update docs/PREFERENCES -> update `backend_routing.py` label and `fusion.py` handoff -> adapt the two freecad tests -> only then mark the community dir legacy.
