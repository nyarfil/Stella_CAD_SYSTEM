---
name: stella-aicad
description: >-
  Drive AI-CAD (ai-cad-labs) from the Stella CAD System repo. CadQuery
  harness, DFM/DFA tools, 8-view renderer. Use when the user picks AI-CAD
  / aicad, or when extracting AI-CAD pieces into Stella. Not AgentCAD MCP.
---

# Stella 上の AI-CAD

正本は `E:\aiwork\Stella_CAD_SYSTEM\ai-cad-labs`（マウスの `V:\mouse\vendor\ai-cad` ではない）。
Python は **3.13**。AgentCAD の 3.12 venv と混ぜない。

AI-CAD に **サーバは無い**。工具は `python -m tools.<name>`。

## 用意

```powershell
powershell -File scripts\stella\setup-aicad.ps1
powershell -File scripts\stella\aicad-health.ps1
```

Cairo（レンダラ）は `C:\Program Files\GTK3-Runtime Win64\bin` を PATH の先頭に足す。

## 使うとき

1. `ai-cad-labs/AGENTS.md` を読む（役割と工具）。
2. 作業ディレクトリを `ai-cad-labs/` にする。
3. Python は `ai-cad-labs\.venv\Scripts\python.exe`、または:

```powershell
uv --directory ai-cad-labs run python -m tools.<name>
```

4. 成果は `ai-cad-labs/projects/<name>/` だけ。
5. ダッシュボード（5199）はユーザーが求めたときだけ。

## 使わないもの

- AgentCAD MCP（`Stella_Agentcad`）を AI-CAD の代わりに呼ばない
- cadgen / ForgeCAD / OpenSCAD MCP
- `generate_*`（Anthropic キー前提の AgentCAD 生成）

## Stella での位置づけ

AI-CAD から取るもの: 意図の分解、CadQuery 生成、多視点レンダ、DFM/DFA、直しループ。
AgentCAD から取るもの: build123d カーネル、隔離、109 MCP 工具。
いまは **並べて置く**。コードを合体しない。
