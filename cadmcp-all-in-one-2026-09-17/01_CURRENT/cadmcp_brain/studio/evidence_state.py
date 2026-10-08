"""Read-only boundary between historical unknown declarations and measurements.

This view never infers that natural-language uncertainty was resolved.  A
future resolution proposal must bind its own evidence instead of rewriting the
declaration or treating a geometry pass as universal proof.
"""
from __future__ import annotations

from ..req2cad.common import digest


_LARGE_FIELDS={'samples','comparisons','surface_points_mm','nodes','edges','check'}


def _origin(payload):
    supplement=payload.get('supplement')
    if isinstance(supplement,dict):
        return (supplement.get('source_subject_digest'),
                supplement.get('base_build_record_sha256'),'source-measurements.json')
    return payload.get('subject_digest'),payload.get('build_record_sha256'),'measurements.json'


def _provenance(payload,relative_path):
    sha=payload.get('file_hashes',{}).get(relative_path)
    return {'relative_path':relative_path,'registered_sha256':sha,
            'integrity':'registered_hash' if sha else 'legacy_hash_not_registered'}


def _summary(check):
    result={}
    for key,value in check.items():
        if key in _LARGE_FIELDS or key in {'id','verdict','passed','verified','scope','kind','status'}:
            continue
        if isinstance(value,(str,int,float,bool)) or value is None:
            result[key]=value
        elif isinstance(value,list) and len(value)<=16 and all(isinstance(item,(str,int,float,bool)) or item is None for item in value):
            result[key]=list(value)
    return result


def _observation(check,origin,provenance):
    explicitly_unverified=(check.get('verified') is False or
                           check.get('status') in {'not_specified','not_requested','not_recorded','not_recorded_legacy'})
    reported=check.get('verdict')
    if reported not in {'pass','fail','unknown'} and type(check.get('passed')) is bool:
        reported='pass' if check['passed'] else 'fail'
    contradictory=(reported in {'pass','fail'} and type(check.get('passed')) is bool
                   and check['passed'] != (reported=='pass'))
    if contradictory:
        evidence_status='inconsistent'
    elif explicitly_unverified or reported not in {'pass','fail'}:
        evidence_status='unverified'
    else:
        evidence_status='measured'
    return {'check_id':check.get('id','unidentified_check'),'origin':origin,
            'kind':check.get('kind','not_specified'),'reported_verdict':reported or 'unknown',
            'effective_verdict':reported if evidence_status=='measured' else evidence_status,
            'evidence_status':evidence_status,'scope':check.get('scope') or check.get('note'),
            'result_summary':_summary(check),'provenance':provenance}


def build_evidence_state(payload,subject_digest):
    """Derive a compact view from an already revalidated Studio payload."""
    measurements=payload.get('measurements',{})
    origin_subject,origin_record,source_path=_origin(payload)
    origin_subject=origin_subject or subject_digest
    declarations=[]
    for ordinal,text in enumerate(measurements.get('unverified_requirements',[])):
        identity={'source_subject_digest':origin_subject,'source_build_record_sha256':origin_record,
                  'ordinal':ordinal,'text':text}
        declarations.append({'declaration_id':digest(identity),'ordinal':ordinal,'text':text,
                             'declaration_preserved':True,'resolution_assessment':'not_assessed',
                             'origin_subject_digest':origin_subject,
                             'origin_build_record_sha256':origin_record,
                             'provenance':_provenance(payload,source_path)})
    observations=[_observation(check,'source_check',_provenance(payload,source_path))
                  for check in measurements.get('checks',[]) if isinstance(check,dict)]
    supplemental=measurements.get('supplemental_acceptance')
    if isinstance(supplemental,dict):
        observations.extend(_observation(check,'supplemental_check',
                                         _provenance(payload,'supplement-report.json'))
                            for check in supplemental.get('checks',[]) if isinstance(check,dict))
    return {'schema_version':1,'historical_declarations':declarations,
            'current_observations':observations,
            'resolution_boundary':{
                'automatic_resolution':False,
                'statement':'Measurements are observations, not automatic resolutions of natural-language declarations. Geometry pass does not prove physical performance, manufacturing, missing inputs or every clause of a compound declaration.',
                'next_step':'A later resolution proposal must identify declaration IDs and bind new evidence; this view is not a completed resolution ledger.'}}
