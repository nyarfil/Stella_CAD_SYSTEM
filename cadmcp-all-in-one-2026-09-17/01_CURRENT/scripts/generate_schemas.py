"""Regenerate or check published contracts from the runtime's exact registries."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from cadmcp_brain.api import Tools
from cadmcp_brain.engine import Brain
from cadmcp_brain.models import SCHEMAS
from cadmcp_brain.studio.mixin import studio_schemas
from cadmcp_brain.req2cad.common import atomic_json


def documents():
    result={name+'.schema.json':model.model_json_schema()
            for name,model in {**SCHEMAS,**studio_schemas()}.items()}
    with tempfile.TemporaryDirectory(prefix='cadmcp-schema-') as temporary:
        result['mcp-tools.json']=Tools(Brain(temporary)).list()
    return result


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check',action='store_true')
    args=parser.parse_args(argv)
    changed=[]
    for name,value in documents().items():
        path=ROOT/'schemas'/name
        try:
            matches=path.is_file() and json.loads(path.read_text('utf-8'))==value
        except (json.JSONDecodeError, UnicodeDecodeError):
            matches=False
        if not matches:
            changed.append(name)
            if not args.check:
                atomic_json(path,value)
    print(json.dumps({'mode':'check' if args.check else 'generate','changed':changed}))
    return int(args.check and bool(changed))


if __name__=='__main__':raise SystemExit(main())
