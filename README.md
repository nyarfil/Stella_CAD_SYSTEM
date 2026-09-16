# Stella CAD System

3D の部品を、**Python の小さなプログラム**として作るための道具です。

普通の CAD は画面をクリックして形を作ります。Stella では「幅 80mm、高さ 20mm の箱」のように、数値と手順をコードに書きます。書いたコードは本物の立体計算エンジン（build123d / OpenCascade）が検査するので、「見た目だけ正しそう」な形は通りません。

いまの第一弾は、本家 [AgentCAD](https://github.com/n3r/AgentCAD) を Windows で安定して動かし、Cursor（Grok）と Codex から同じ工具を呼べるようにすることです。

## 第一弾の範囲

やる:

- AgentCAD 本体を `agentcad-for-windows/` に置く
- Windows で隔離（AppContainer）をオンにしたまま起動する
- Cursor / Codex が、本家が Claude Code に出していたのと同じ MCP 工具を呼ぶ（Anthropic のキーは不要）

まだやらない:

- Fusion MCP、AI-CAD、ForgeCAD、text-to-cad との合体
- ブラウザの内蔵チャット（Anthropic キー前提）を別モデルに差し替えること

## フォルダの意味

```
Stella_CAD_SYSTEM/
  agentcad-for-windows/   立体の計算エンジン（本家のコピー）
  stella_cad/             橋 CLI と MCP 入口
  .cursor/mcp.json        Cursor 用 AgentCAD MCP（このリポだけ）
  .codex/config.toml      Codex 用 AgentCAD MCP（このリポだけ）
  scripts/stella/         Windows 用の起動・セットアップ
  projects/               作った部品の保存先（Git には入れない）
  AGENTS.md               エージェントが最初に読む手順
  UPSTREAM.md             本家のどの版を取り込んだか
```

## 最初にやること

1. Python 3.12 と [uv](https://docs.astral.sh/uv/) を入れる
2. セットアップ:

```powershell
powershell -File scripts\stella\setup.ps1
```

3. サーバ起動:

```powershell
powershell -File scripts\stella\serve.ps1
```

ブラウザで `http://127.0.0.1:8630` が開けます（そこが別プロセスなら 8640）。Cursor と Codex は MCP サーバ `agentcad` で同じカーネルに繋がります。MCP がサーバを起こします。

## エージェントから使う

正は MCP の工具を直接呼ぶことです（Claude Code の `claude mcp add agentcad` と同じ面）。MCP が無いときだけ橋:

```powershell
uv run python -m stella_cad.bridge health
uv run python -m stella_cad.bridge list
uv run python -m stella_cad.bridge call create_project --args "{""name"": ""demo""}"
```

くわしい呼び方・部品の書き方・失敗の読み方は [AGENTS.md](AGENTS.md) にあります。
