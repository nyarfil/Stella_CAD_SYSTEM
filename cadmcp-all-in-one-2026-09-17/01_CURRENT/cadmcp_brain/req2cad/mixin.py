"""Adds the knowledge-base tools to the existing registry; no second CAD authority."""
from __future__ import annotations
import os
from pathlib import Path
from .catalog import Catalog
from .service import Service
from ..errors import BrainError


def catalog_for(brain):
    return Catalog(os.environ.get('CADMCP_REQ2CAD_ROOT',str(brain.store.root/'knowledge'/'req2cad')))

class Req2CADToolsMixin:
    def _fs(self):return Service(catalog_for(self.brain))

    def brain_fs_status(self) -> dict:
        """Read actual function/asset/geometry coverage. An empty catalog is not an installed 128k library."""
        return catalog_for(self.brain).status()

    def brain_fs_search(self,functions: list[str],limit: int=20,threshold: float=0.7,require_cad: bool=False,mode: str='semantic') -> dict:
        """Retrieve real CAD UIDs by functional keywords. Semantic is default and requires a prepared real model/index. Lexical mode must be explicitly requested."""
        c=catalog_for(self.brain)
        if mode=='lexical':return c.lexical(functions,limit,require_cad)
        if mode!='semantic':raise BrainError('FS_ARGUMENT','Use semantic or explicit lexical.')
        from .semantic import SemanticIndex
        return SemanticIndex(c).search(functions,self._fs_get_encoder(c),threshold,limit,require_cad)

    def _fs_get_encoder(self,c):
        from .semantic import SentenceEncoder
        config=c.root/'encoder_config.json'
        if not config.exists():raise BrainError('FS_ENCODER_NOT_CONFIGURED','Run owner-side setup for the embedding model. No paid API or fake embedding fallback is used.')
        from .common import json_load
        conf=json_load(config)
        identity=(str(config),config.stat().st_mtime_ns)
        if getattr(self,'_fs_encoder_identity',None)!=identity:
            from .semantic import verify_model
            verify_model(conf['model_path'])
            self._fs_encoder=SentenceEncoder(conf['model_path'],device=conf.get('device','cpu'),batch_size=conf.get('batch_size',8),query_mode=conf.get('query_mode','req2cad_native'))
            self._fs_encoder_identity=identity
        return self._fs_encoder

    def brain_fs_case(self,uid: str) -> dict:
        """Read exact original functional annotation and linked asset metadata. Labels are hypotheses, not verified engineering capabilities."""
        return catalog_for(self.brain).case(uid)

    def brain_fs_materialize(self,uid: str,timeout_seconds: int=60) -> dict:
        """Reconstruct/import the registered real CAD; export STEP/STL/views and measure face-type graph, WL features and sampled geometry. Never invent geometry for missing UIDs."""
        return self._fs().materialize(uid,timeout_seconds)

    def brain_fs_evidence(self,uid: str) -> dict:
        """Return source-hashed function + geometry + topology evidence, usable in Concept.case_references. Requires original file integrity; no strength claims."""
        return self._fs().evidence(uid)

    def brain_fs_compare(self,uid_a: str,uid_b: str) -> dict:
        """Compare actual materialized face-adjacency topology (WL) and surface geometry descriptors. Not a functional equivalence or automatic assembly proof."""
        return self._fs().compare(uid_a,uid_b)

    def brain_fs_portfolio(self,uids: list[str],mode: str='topology',limit: int=6) -> dict:
        """Choose structurally diverse representatives from retrieved, measured CAD UIDs. Missing geometry is reported, not fabricated."""
        return self._fs().portfolio(uids,mode,limit)
