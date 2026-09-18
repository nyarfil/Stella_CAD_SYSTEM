"""Compact engineering state for model handoffs; full evidence stays on disk."""
from __future__ import annotations
import copy

def compact_subject(info):
    result=copy.deepcopy(info);payload=result['payload']
    if payload.get('kind')!='recipe_build':return result
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
    payload['full_evidence_file']=payload['folder']+'/build-record.json'
    result['context_compaction_notice']='Sample arrays and very large graphs are summarized; immutable full files remain available. Summary is not additional measurement.'
    return result
