# Stella CAD System

ユーザーの意図を汲み取り、いい感じに自動で 3D モデリングするための作業リポです。

手元の複数プロジェクト（AgentCAD、AI-CAD、text-to-cad、ForgeCAD、Fusion、OpenSCAD）から **良い部分だけ** を抜き、一本の支援ツールにします。いまはその部品を並べて、Windows で動くことを確かめる段階です。合体はまだしません。

普通の CAD は画面をクリックして形を作ります。Stella が目指すのは、「こういう部品が欲しい」と言ったら、意図を読み、コードで形を作り、本物の立体計算で検査し、直して、STEP まで出すことです。

## いまあるエンジン

| 置き場 | 役割 | Python |
|---|---|---|
| `agentcad-for-windows/` | build123d カーネル、隔離、Cursor/Codex の 109 MCP 工具 | 3.12 |
| `ai-cad-labs/` | CadQuery、多視点レンダ、DFM/DFA、複数エージェントの設計ループ | 3.13 |
| `text-to-cad/` | cadgen。自然言語・図面・画像からパラメトリック、STEP 検査 | 3.13 |
| `forgecad/` | ForgeCAD。`.forge.js`、組み立て、CLI（npm 0.13.0） | Node 20+ |

venv は混ぜません。

## 第一弾の範囲（下ごしらえ）

やる:

- 各エンジンをこのリポに置き、Windows で動かす
- AgentCAD は隔離（AppContainer）オンのまま MCP `Stella_Agentcad` で呼ぶ
- AI-CAD はサーバ無し。`python -m tools.<name>` で呼ぶ
- text-to-cad はサーバ無し。`cadgen` と `text-to-cad/skills/` で呼ぶ
- ForgeCAD はサーバ無し。`node forgecad/node_modules/forgecad/dist-cli/forgecad.js`

まだやらない:

- コードを一つのカーネルに混ぜること
- Fusion MCP の取り込み
- ブラウザ内蔵チャットを別モデルに差し替えること

## フォルダの意味

```
Stella_CAD_SYSTEM/
  agentcad-for-windows/   AgentCAD 本体
  ai-cad-labs/            AI-CAD (ai-cad-labs) 本体
  text-to-cad/            text-to-cad / cadgen 本体
  forgecad/               ForgeCAD CLI（npm ピン）
  stella_cad/             AgentCAD の橋 CLI と MCP 入口
  .cursor/mcp.json        Cursor 用 Stella_Agentcad MCP（このリポだけ）
  .codex/config.toml      Codex 用 Stella_Agentcad MCP（このリポだけ）
  scripts/stella/         Windows 用の起動・セットアップ
  projects/               AgentCAD で作った部品（Git には入れない）
  AGENTS.md               エージェントが最初に読む手順
  UPSTREAM.md             本家のどの版を取り込んだか
```

## 最初にやること

1. Python 3.12 / 3.13 と [uv](https://docs.astral.sh/uv/) を入れる
2. AgentCAD:

```powershell
powershell -File scripts\stella\setup.ps1
powershell -File scripts\stella\serve.ps1
```

3. AI-CAD:

```powershell
powershell -File scripts\stella\setup-aicad.ps1
powershell -File scripts\stella\aicad-health.ps1
```

4. text-to-cad:

```powershell
powershell -File scripts\stella\setup-text-to-cad.ps1
powershell -File scripts\stella\text-to-cad-health.ps1
```

5. ForgeCAD:

```powershell
powershell -File scripts\stella\setup-forgecad.ps1
powershell -File scripts\stella\forgecad-health.ps1
```

ブラウザで AgentCAD は `http://127.0.0.1:8630`（そこが別プロセスなら 8640）。AI-CAD のダッシュボード（5199）は、求められたときだけ `ai-cad-labs/frontend` で起動します。

Cursor と Codex の MCP 名は **`Stella_Agentcad`** です。本家 n3r/AgentCAD の MCP は登録しません。

## エージェントから使う

AgentCAD の正は MCP 工具を直接呼ぶことです。手順は [AGENTS.md](AGENTS.md)。AI-CAD は `.cursor/skills/stella-aicad/SKILL.md`。text-to-cad は `.cursor/skills/stella-text-to-cad/SKILL.md`。ForgeCAD は `.cursor/skills/stella-forgecad/SKILL.md`。
