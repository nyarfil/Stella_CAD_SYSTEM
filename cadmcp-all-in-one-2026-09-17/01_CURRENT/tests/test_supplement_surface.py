"""Supplementary measurements must be visible through the shared public surface."""
from cadmcp_brain.api import Tools
from cadmcp_brain.studio.packets import evidence_attachments


def test_supplement_tool_is_explicit_local_write_and_spec_is_discoverable(brain):
    tools = Tools(brain)
    entries = {entry['name']: entry for entry in tools.list()}
    tool = entries['brain_studio_verify_artifact']
    assert tool['annotations'] == {
        'readOnlyHint': False, 'destructiveHint': False, 'openWorldHint': False,
    }
    assert tools.brain_studio_schema('AcceptanceSpec')['title'] == 'AcceptanceSpec'


def test_supplement_packet_requires_source_and_additional_measurements(tmp_path):
    names = ['measurements.json', 'assembly.png', 'source-build-record.json',
             'source-measurements.json', 'supplement-spec.json', 'supplement-report.json']
    payload = {'kind': 'recipe_build', 'folder': str(tmp_path),
               'build_record_sha256': 'a' * 64,
               'file_hashes': {name: 'b' * 64 for name in names},
               'supplement': {'cad_regenerated': False}}
    attachments = evidence_attachments(payload)
    paths = {item['path'] for item in attachments}
    assert paths == {str(tmp_path / name) for name in names + ['build-record.json']}
    assert all(item['sha256'] in ('a' * 64, 'b' * 64) for item in attachments)


def test_delivery_verified_supplement_attaches_registered_part_manifest(tmp_path):
    payload={'kind':'recipe_build','folder':str(tmp_path),
             'file_hashes':{'delivery-manifest.json':'c'*64},
             'supplement':{'delivery_consistency_required':True}}
    assert evidence_attachments(payload)==[
        {'kind':'json','path':str(tmp_path/'delivery-manifest.json'),'sha256':'c'*64}]
    # Packet construction never re-hashes potentially modified evidence.
    (tmp_path/'delivery-manifest.json').write_text('modified',encoding='utf-8')
    assert evidence_attachments(payload)[0]['sha256']=='c'*64
