# cadMCP Design Studio 0.3.3 — Shell pack and structure intake

Adds fail-closed Board Packs and Shell Packs on top of 0.3.1 Cursor/MCP support.
A ready board alone does not start structure generation.
Req2CAD retrieval, typed recipes and five-role review are unchanged.


Incremental Cursor IDE + MCP integration and Cursor Agent CLI provider for the
existing real Function–Structure retrieval, typed CAD and multi-role review path.

[日本語のCursor導入手順](CURSOR_GUIDE_JA.md) · [検証記録](TEST_REPORT_JA.md)

No Codex dependency in IDE mode or when explicitly using `--provider cursor`.
The CLI provider requests ask mode, validates the terminal envelope AND native
engineering JSON, stages evidence and keeps the original bounded CAD executor.
Native Cursor reviewer definitions are included. Real GUI/account/model execution
is not certified; documented test doubles are distinct from live-model evaluation.
