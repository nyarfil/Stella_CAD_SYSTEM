# NOTICE - third-party code in this directory

`addin/STEVE/` is a vendored copy of the Autodesk Fusion add-in **STEVE** by 10-X-eng and STEVE contributors.

- Upstream: https://github.com/10-X-eng/STEVE
- Commit: `17e684e` (2026-09-30), add-in manifest version `0.8.1`
- License: MIT. Full text: [THIRD_PARTY_STEVE_LICENSE.txt](THIRD_PARTY_STEVE_LICENSE.txt). Upstream `licenses/` (Codex runtime notice) is kept in [THIRD_PARTY_LICENSES/](THIRD_PARTY_LICENSES/).
- Source of the copy: a read-only clone of upstream `addin/STEVE/` (everything under it, byte-identical except as listed below). Nothing outside `addin/STEVE/` was vendored: upstream `scripts/` (including `fetch_runtime.py`), `tests/`, `docs/`, installer and CI are NOT included. The Codex runtime (`addin/STEVE/runtime/`) is NOT included; it is fetched separately by the owner (see README_STELLA_JA.md).

Per-file license headers were deliberately not added to the vendored files, to keep the diff against upstream minimal and reviewable. This file and `docs/patches/rmfg-removal-and-seam.diff` are the provenance record. The complete, machine-generated diff (upstream -> this tree) is the authoritative change list.

## Changes against upstream 17e684e

### 1. Removed: RMFG (sheet-metal supplier DFM / quotes / checkout)

Deleted files (all in `addin/STEVE/steve/`):
`rmfg.py`, `rmfg_checkout.py`, `rmfg_connection.py`, `rmfg_jobs.py`, `rmfg_service.py`, `rmfg_snapshot.py`.
(`rmfg.py` contained the only `api.rmfg.com` reference; no such string remains - `grep -ri rmfg addin/` is empty.)

Edited files (removals only; CRLF line endings preserved):

| File | What was removed |
|---|---|
| `steve/tool_protocol.py` | the `rmfg_checkout`, `rmfg_materials`, `fusion_rmfg` entries of `TOOLS`; recovery texts `rmfg_export_scope`, `rmfg_unavailable`; the three `rmfg` branches of `validate_call` |
| `steve/fusion_tools.py` | `from .rmfg_snapshot import export_snapshot`; `"fusion_rmfg"` in the read-allowed tool tuple of `check_command`; method `rmfg_snapshot`; the `fusion_rmfg` branch of `drain` |
| `steve/controller.py` | RMFG imports; `rmfg_state` parameter of `manufacturing_context` (and the `rmfgConnection` context key); state keys `rmfgState/Busy/Error/Code/CheckoutEnabled/Checkout`; `RMFGConnection`/`RMFGService` construction, `rmfg.action('rmfgRefresh')`, `close()` calls; actions `rmfgOpenCheckout`, `rmfgConnect/EnableCheckout/Refresh/Disconnect/Cancel`; `rmfg_checkout` result handling; RMFG tool names from the DFM-enabled guard and activity titles; the `rmfg_service.submit` dispatch branch; `rmfgBusy/rmfgCheckoutOpening` from the update-idle condition |
| `steve/dfm.py` | the sheet-metal `supplier` guide text, and the RMFG sentence in the sheet-metal `unchecked` text (now: native checks only) |
| `panel/index.html` | RMFG settings subsection, the "Reconnect" badge, the RMFG checkout bar |
| `panel/panel.js` | all `rmfg-*` DOM updates and click handlers, the RMFG summary in the Manufacturing row |

Kept as upstream: the DFM switch and all native (local) DFM planning/checks (`dfm.py`, `dfm_geometry.py`, `machines.py`, `fusion_dfm_plan`, `fusion_dfm_check`). They do not talk to any network service. The now-unused CSS class `.supplier-checkout` remains in `panel/style.css` (inert).

### 2. Added: Stella seam (the ONLY functional addition)

- New file `addin/STEVE/steve/stella_seam.py` (clearly marked, ~190 lines): loopback `127.0.0.1` HTTP server + bearer token that calls STEVE's own `validate_call`, then `FusionTools.submit`. Opt-in (starts only if `<STEVE data>/stella-seam/config.json` has `{"enabled": true}`).
- One hook line in `addin/STEVE/STEVE.py` (line 275, marked `# STELLA SEAM hook`), directly after `_fusion_tools = FusionTools(_app)`. The hook is a 4-line try/except calling `safe_start`, so a seam failure never aborts `run()`. The seam wraps `fusion_tools.close` and `fusion_tools.run_script` (to drop `context['data']` for Stella jobs only); no upstream function body is changed.

Nothing else in STEVE was changed: no feature other than RMFG was disabled or altered, and no defaults were changed (updater, web search, provider, debug logging: see docs/DESIGN.md section 9).

## Stella-authored (not third-party)

`server/` (guard layer + stdio MCP server), `tests/`, `docs/`, `README_STELLA_JA.md`.
- Modified `addin/STEVE/steve/claude_setup.py` `account_status`: also accepts `authMethod: "oauth_token"` (`claude setup-token` / CLAUDE_CODE_OAUTH_TOKEN logins), which are subscription auth without a plan type. API-key/base-URL overrides are still rejected.
- Modified `claude_setup.resolve_claude`: on Windows prefer `~/.local/bin/claude.exe` (native) over an older npm `claude.CMD` earlier on PATH.
- Modified `claude_setup`: `resolve_claude` picks the newest installed Claude Code (desktop-app bundle, native installer, PATH); `discover_models` returns the fixed subscription picker Opus 5.5 / Sonnet 5.5 / Haiku 5.5 (default Sonnet 5.5, no 1M variants) and refuses Claude Code < 2.1.280. Reason: the 2.1.117 CLI lacks the zero-turn history replay STEVE needs and cannot serve Claude 5.5.
