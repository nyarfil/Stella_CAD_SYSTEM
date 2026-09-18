"""Explicit owner-side full annotation + local embedding setup.

No CAD-source units are guessed. Supplying --cad-path links the actual source data.
The final report distinguishes annotations/embeddings from available/measured CAD.
"""
from __future__ import annotations
import argparse, json, os, subprocess, sys
from pathlib import Path
from bootstrap import ROOT,python_in,run,write_configs,atomic_text
sys.path.insert(0,str(ROOT))

def parser():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--workspace',type=Path,default=ROOT/'workspace')
    p.add_argument('--csv',type=Path,help='Use an already downloaded original Req2CAD.csv')
    p.add_argument('--cad-path',type=Path,help='Original DeepCAD data.tar, cad_json directory, or matching-UID STEP directory')
    p.add_argument('--cad-kind',choices=['deepcad_tar','deepcad_json','step'],default='deepcad_tar')
    p.add_argument('--download-deepcad',action='store_true',help='Download the original archive explicitly, then link it by exact UID')
    p.add_argument('--reference-only',action='store_true',help='Use CAD as uncalibrated structure references; no physical source units need be guessed')
    p.add_argument('--scale-to-mm',type=float)
    p.add_argument('--unit-basis',help='Evidence for the input unit conversion; never guess dataset source units')
    p.add_argument('--model',default='Qwen/Qwen3-Embedding-4B')
    p.add_argument('--revision',help='Optional exact upstream model revision')
    p.add_argument('--device',choices=['auto','cpu','cuda'],default='auto')
    p.add_argument('--batch-size',type=int,default=8)
    p.add_argument('--skip-install',action='store_true',help='Use existing .venv with installed [geometry,semantic] extras')
    p.add_argument('--allow-ungrounded-drafts',action='store_true',help='Disable the real-case-required gate; not the default')
    return p

def main(argv=None):
    p=parser();a=p.parse_args(argv)
    if a.cad_path and a.download_deepcad:p.error('Choose --cad-path or --download-deepcad, not both')
    if (a.cad_path or a.download_deepcad) and not a.reference_only and (a.scale_to_mm is None or not a.unit_basis):p.error('--cad-path requires --scale-to-mm and --unit-basis')
    if a.batch_size<1 or a.batch_size>64:p.error('--batch-size must be 1–64')
    py=python_in(ROOT/'.venv')
    if not py.exists():
        import venv
        venv.EnvBuilder(with_pip=True).create(ROOT/'.venv')
    try:
        if not a.skip_install:run([str(py),'-m','pip','install',str(ROOT)+'[geometry,semantic]'])
        root=a.workspace.resolve()/'knowledge'/'req2cad'
        base=[str(py),'-m','cadmcp_brain.req2cad','--root',str(root)]
        if a.csv:
            # Local copies must match the inspected official original, not a substitute fixture.
            from cadmcp_brain.req2cad.common import REQ_SHA256
            run(base+['ingest',str(a.csv.resolve()),'--expected-sha256',REQ_SHA256])
        else:run(base+['download-annotations'])
        if a.download_deepcad:
            run(base+['download-deepcad']);a.cad_path=root/'downloads'/'data.tar';a.cad_kind='deepcad_tar'
        if a.cad_path:
            units=['--reference-only'] if a.reference_only else ['--scale-to-mm',str(a.scale_to_mm),'--unit-basis',a.unit_basis]
            run(base+['attach-cad',str(a.cad_path.resolve()),'--kind',a.cad_kind]+units)
        device=a.device
        if device=='auto':
            device=subprocess.check_output([str(py),'-c',"import torch;print('cuda' if torch.cuda.is_available() else 'cpu')"],text=True).strip()
        cmd=base+['install-model','--model',a.model,'--device',device,'--batch-size',str(a.batch_size)]
        if a.revision:cmd+=['--revision',a.revision]
        run(cmd);run(base+['build-embeddings','--batch-size',str(a.batch_size)])
        run(base+['verify-index'])
        destination=ROOT/'integration'/'generated'
        entry=write_configs(py,a.workspace,destination)
        entry['env']['CADMCP_REQ2CAD_ROOT']=str(root)
        entry['env']['CADMCP_REQUIRE_CAD_REFERENCES']='0' if a.allow_ungrounded_drafts else '1'
        atomic_text(destination/'cursor.mcp.json',json.dumps({'mcpServers':{'cadmcp-design-brain':entry}},ensure_ascii=False,indent=2)+'\n')
        toml=(destination/'codex.config.toml').read_text('utf-8')
        toml+='CADMCP_REQ2CAD_ROOT = '+json.dumps(str(root),ensure_ascii=False)+'\nCADMCP_REQUIRE_CAD_REFERENCES = '+json.dumps(entry['env']['CADMCP_REQUIRE_CAD_REFERENCES'])+'\n'
        atomic_text(destination/'codex.config.toml',toml)
        run(base+['status'])
        print('Annotation + embedding setup complete. CAD linking/build coverage is shown above; this is not a full-library geometry-success claim.')
        print('Merge only the generated MCP entry into your existing client configuration. Existing CAD servers were not changed.')
        return 0
    except (OSError,ValueError,subprocess.CalledProcessError) as exc:
        print('Req2CAD setup stopped; no complete-library success claimed: '+str(exc),file=sys.stderr)
        print('Downloaded verified files/checkpoints remain for retry. Never replace missing data with synthetic fixtures.',file=sys.stderr)
        return 1

if __name__=='__main__':raise SystemExit(main())
