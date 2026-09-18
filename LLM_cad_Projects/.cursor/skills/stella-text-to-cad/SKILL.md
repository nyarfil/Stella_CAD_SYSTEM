---
name: stella-text-to-cad
description: >-
  Drive earthtojake/text-to-cad (cadgen) from the Stella CAD System repo.
  Natural-language / image / drawing to parametric build123d, STEP inspect,
  snapshots. Use when the user picks text-to-cad / cadgen. Not AgentCAD MCP,
  not AI-CAD CadQuery.
---

# Stella 上の text-to-cad

正本は `E:\aiwork\Stella_CAD_SYSTEM\text-to-cad`。
マウスの `V:\mouse\.venv-text-to-cad` は使わない。
cookbook は `text-to-cad/skills/` にある。`.cursor/skills` にコピーしない。

エンジンは **cadgen**（build123d）。Python は **3.13** の別 venv。

## 用意

```powershell
powershell -File scripts\stella\setup-text-to-cad.ps1
powershell -File scripts\stella\text-to-cad-health.ps1
```

## 使うとき

1. `text-to-cad/skills/cad/SKILL.md` を読む（必要なら cad-viewer / dxf / dfam-check）。
2. Python / CLI:

```powershell
text-to-cad\.venv\Scripts\python.exe
text-to-cad\.venv\Scripts\cadgen.exe
```

3. モデルは `python <model>.py`。検査は `cadgen step inspect` など。スクリプトは実行し、コマンドはファイル（STEP 等）を見る。
4. スナップショットは Playwright Chromium が要る。未導入ならユーザーが求めたときだけ `python -m playwright install chromium`。

## 使わないもの

- AgentCAD MCP と AI-CAD の CadQuery 工具を混ぜない
- ForgeCAD / OpenSCAD MCP
- 本家 Skill 一式を `.cursor/skills` にコピーすること
