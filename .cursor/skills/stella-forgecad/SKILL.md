---
name: stella-forgecad
description: >-
  Drive ForgeCAD from the Stella CAD System repo (.forge.js, assembly,
  export). Use when the user picks ForgeCAD. Not AgentCAD MCP, not AI-CAD,
  not cadgen.
---

# Stella 上の ForgeCAD

正本の CLI は `E:\aiwork\Stella_CAD_SYSTEM\forgecad`（npm ピン `forgecad@0.13.0`）。
グローバル PATH の `forgecad` は使わない。

ForgeCAD は JavaScript の `.forge.js`。Python の venv は無い。

## 用意

```powershell
powershell -File scripts\stella\setup-forgecad.ps1
powershell -File scripts\stella\forgecad-health.ps1
```

## 使うとき

1. cookbook が要るときはユーザー側の `forgecad` Skill（`.agents/skills/forgecad`）を読む。Stella にはコピーしない。
2. CLI:

```powershell
node forgecad\node_modules\forgecad\dist-cli\forgecad.js run path\to\model.forge.js
```

3. 成果は Stella の作業フォルダに書く。`forgecad/smoke/` はヘルス用の箱だけ。

## 使わないもの

- AgentCAD MCP / AI-CAD CadQuery / cadgen を混ぜない
- OpenSCAD MCP
- 本家 Skill 一式を `.cursor/skills` にコピーすること

## ライセンス

npm の ForgeCAD は独自ライセンスです。個人の非商用は無料。商用やエージェントから自動で呼ぶ用途は本家の Pro / Enterprise を確認する。並べて比較するための置き場であり、権利を無視して埋め込む前提ではない。
