"""Offline evidence page; no remote JS, telemetry or destructive controls."""
from __future__ import annotations
import html,json,shutil
from pathlib import Path

def build_report(folder,record,service):
    folder=Path(folder);report=record['measurements'];recipe=record['context']['recipe']
    esc=lambda x:html.escape(str(x),quote=True)
    use_labels={'principle_reference':'原理の参考（形状流用を意味しない）',
                'fit_reference':'寸法・接続面の適合参考','direct_reuse':'形状の直接流用'}
    reference_uses=''.join(
        f'<article><h3>{esc(use_labels.get(use["use"],use["use"]))}</h3>'
        f'<p>参照: {esc(use["uid"])} / 機能: {esc(use["function_id"])}</p>'
        f'<p>{esc(use["application"])}</p><p class="muted">参照STEP SHA256: {esc(use["cad_sha256"])}</p></article>'
        for use in report.get('reference_uses',[]))
    sections=[]
    for uid in record['context']['reference_digests']:
        if uid.startswith('project:'):continue
        evidence=service.evidence(uid);g=evidence['geometry'];dest=folder/'references'/uid.replace('/','_');dest.mkdir(parents=True,exist_ok=True)
        for name in ['iso.svg','top.svg','front.svg','right.svg','iso.png','top.png','front.png','right.png']:
            shutil.copyfile(g['exports'][name]['absolute_path'],dest/name)
        pre=json.dumps(g.get('interfaces',{}),ensure_ascii=False,indent=2)
        images=''.join(f'<img alt="{esc(name)}" src="references/{uid.replace("/","_")}/{name}.png">' for name in ('iso','top','front','right'))
        sections.append(f'<article><h3>{esc(uid)}</h3><p>{esc(", ".join(evidence["function_keywords"]))}</p><p class="muted">機能注釈は仮説。実形状の面・穴・接続を確認する。</p><div class="views">{images}</div><details><summary>測定した接続面・出典</summary><pre>{esc(pre)}</pre><pre>{esc(json.dumps(evidence["citation"],ensure_ascii=False,indent=2))}</pre></details></article>')
    cards=''.join(f'<article><h3>{esc(k)}</h3><img class="part" src="{esc(k)}/iso.png"><p><a href="{esc(k)}/model.step">STEP</a> · <a href="{esc(k)}/model.stl">STL</a></p><p>外接寸法 mm: {esc(v["features"]["bbox_mm"])}</p></article>' for k,v in report['outputs'].items())
    checks=''.join(f'<tr><td>{esc(c["id"])}</td><td>{esc(c["kind"])}</td><td>{esc(c["verdict"])}</td><td>{esc(c.get("distance_mm",c.get("actual_candidates_mm",c.get("actual", "幾何サンプルと距離の下界をJSONに記録"))))}</td></tr>' for c in report['checks'])
    text=f'''<!doctype html><html lang="ja"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src 'self' data:; style-src 'unsafe-inline'; base-uri 'none'">
<title>{esc(recipe['title'])} — 構造設計の根拠</title><style>
body{{font:16px/1.7 system-ui,sans-serif;margin:0;background:#f4f6f8;color:#202d38}}main{{max-width:1100px;margin:auto;padding:38px 24px}}h1{{font-size:30px;line-height:1.35}}h2{{margin-top:40px}}article{{background:white;padding:22px;border:1px solid #d9e1e7;border-radius:8px;margin:18px 0}}.views{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}}img{{max-width:100%;background:white}}.part{{max-height:350px}}.banner{{padding:20px;background:#fff4d9;border-left:4px solid #b47800}}.muted{{color:#586b79}}pre{{white-space:pre-wrap;overflow-wrap:anywhere;font-size:13px;background:#eef2f5;padding:14px}}table{{width:100%;border-collapse:collapse}}td,th{{text-align:left;border-bottom:1px solid #d1dbe4;padding:10px}}a{{color:#14618a}}.outputs{{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:18px}}
</style><main><p class="muted">cadMCP Design Studio 0.3.0 / 構造参照 → 適合設計 → 幾何検査</p>
<h1>{esc(recipe['title'])}</h1><div class="banner"><strong>全体判定: 未検証</strong><br>幾何検査: {esc(report['geometry_checks_verdict'])}。材料・製造・疲労・連続可動域の合格証ではありません。</div>
<h2>元の要求</h2><p>{esc(recipe['original_request'])}</p><p class="muted">根拠識別子: {esc(record['subject_digest'])}</p>
<h2>出力アセンブリ</h2><img alt="assembly view" src="assembly.png"><p><a href="assembly.step">アセンブリSTEP</a> · <a href="recipe.json">編集可能な構築レシピ</a> · <a href="measurements.json">全測定結果JSON</a></p><div class="outputs">{cards}</div>
<h2>実形状で確認した項目</h2><table><tr><th>項目</th><th>方式</th><th>判定</th><th>測定値・範囲</th></tr>{checks}</table>
<h2>未確認の事項</h2><pre>{esc(json.dumps(report['unverified_requirements'],ensure_ascii=False,indent=2))}</pre>
<h2>参考の使い方</h2><p>以下は設計者が記録した利用意図です。参考の存在だけでは機構の有効性・適合・性能を証明しません。</p>{reference_uses or '<p>明示的な利用区分の記録なし。直接流用したとは推定しません。</p>'}
<h2>参照CADと構造の根拠</h2>{''.join(sections)}
<h2>何を変更したか</h2><pre>{esc(json.dumps(report['trace'],ensure_ascii=False,indent=2))}</pre>
<p class="muted">このページはローカルの読取専用成果物です。プリンタ送信、CAD正本の書換え、外部通信は行いません。</p></main></html>'''
    p=folder/'EVIDENCE_REVIEW.html';p.write_text(text,encoding='utf-8');return p
