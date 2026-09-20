"""Compact engineering state for model handoffs; full evidence stays on disk."""
from __future__ import annotations
import copy
from pathlib import Path

def evidence_attachments(payload):
    """Return the attachment manifest registered with the review subject.

    This deliberately does not hash files at packet time.  A packet must not
    turn a modified file into a newly "valid" attachment merely by observing
    its new digest.  Pre-hash subjects remain readable, but are not eligible
    for an evidence-complete owner discussion.
    """
    if payload.get('kind')!='recipe_build':return []
    folder=Path(payload['folder']).resolve();hashes=payload.get('file_hashes',{})
    names=['measurements.json','assembly.png']
    if payload.get('supplement'):
        names.extend(['source-build-record.json','source-measurements.json',
                      'supplement-spec.json','supplement-report.json'])
        if payload['supplement'].get('delivery_consistency_required') is True:
            names.append('delivery-manifest.json')
    names.extend(name for name in hashes if name.endswith('/iso.png'))
    result=[]
    build_record_sha256=payload.get('build_record_sha256')
    if build_record_sha256:
        result.append({'kind':'json','path':str(folder/'build-record.json'),'sha256':build_record_sha256})
    for name in names:
        if name in hashes:
            result.append({'kind':'image' if name.endswith('.png') else 'json',
                           'path':str(folder/name),'sha256':hashes[name]})
    # A path is an attachment identity as well as a digest.  Different files
    # can legitimately have the same bytes, and must each be inspected.
    return sorted(result,key=lambda item:(item['path'],item['sha256']))

def compact_subject(info):
    result=copy.deepcopy(info);payload=result['payload']
    if payload.get('kind')!='recipe_build':return result
    from .evidence_state import build_evidence_state
    payload['evidence_state']=build_evidence_state(payload,result['subject_digest'])
    m=payload['measurements']
    for output in m.get('outputs',{}).values():
        f=output['features']
        for key in ['wl_features','surface_geometry','geometry_descriptor','surface_points_mm']:
            f.pop(key,None)
        topology=f.get('topology')
        if topology and len(topology.get('nodes',[]))>128:
            f['topology_summary']={'nodes':len(topology['nodes']),'edges':len(topology.get('edges',[])),'full_graph':'Read measurements.json from the immutable build folder.'}
            del f['topology']
        ports=f.get('interfaces',{}).get('ports',[])
        if len(ports)>128:
            f['interfaces']['ports']=ports[:128]
            f['interfaces']['ports_truncated']=True;f['interfaces']['total_ports']=len(ports)
    for check in m.get('checks',[]):
        samples=check.pop('samples',None)
        if samples:
            check['samples_evaluated']=len(samples)
            check['minimum_distance_sample']=min(samples,key=lambda s:s['distance_mm'])
            check['maximum_overlap_sample']=max(samples,key=lambda s:s['overlap_mm3'])
            check['failed_samples']=sum(s['verdict']=='fail' for s in samples)
            check['full_samples']='Read measurements.json from the immutable build folder.'
    payload['evidence_attachments']=evidence_attachments(payload)
    result['context_compaction_notice']='Sample arrays and very large graphs are summarized; immutable full files remain available. Summary is not additional measurement.'
    return result
