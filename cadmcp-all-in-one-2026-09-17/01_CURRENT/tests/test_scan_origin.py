"""brain_mouse_scan_origin: user-chosen scan origin branch (real_scan | fused_original)."""
from __future__ import annotations

import pytest

from cadmcp_brain.api import Tools
from cadmcp_brain.engine import Brain
from cadmcp_brain.errors import BrainError


def T(ws):
    return Tools(Brain(ws))


def test_unset_needs_user_choice_and_lists_both_origins(tmp_path):
    r = T(tmp_path).call('brain_mouse_scan_origin', {})
    assert r['status'] == 'NEEDS_USER_CHOICE' and r['automatic_choice'] is False and r['selection'] is None
    assert set(r['origins']) == {'real_scan', 'fused_original'}
    assert 'findmymouse' in r['question_en'] and r['question_ja']
    fused = r['origins']['fused_original']['pipeline']
    assert [s['implemented'] for s in fused][:2] == [True, True] and not all(s['implemented'] for s in fused)
    assert all(s['implemented'] for s in r['origins']['real_scan']['pipeline'])


def test_select_clear_roundtrip_is_workspace_local(tmp_path, tmp_path_factory):
    t = T(tmp_path)
    s = t.call('brain_mouse_scan_origin', {'action': 'select', 'origin': 'fused_original', 'reason': 'user said so'})
    assert s['status'] == 'SELECTED' and s['selection']['origin'] == 'fused_original' and s['active_pipeline']
    assert (tmp_path / '.cadmcp/scan-origin.json').is_file()
    assert T(tmp_path).call('brain_mouse_scan_origin', {})['selection']['reason'] == 'user said so'
    assert T(tmp_path_factory.mktemp('other')).call('brain_mouse_scan_origin', {})['status'] == 'NEEDS_USER_CHOICE'
    assert t.call('brain_mouse_scan_origin', {'action': 'clear'})['status'] == 'NEEDS_USER_CHOICE'


def test_invalid_origin_rejected(tmp_path):
    t = T(tmp_path)
    with pytest.raises(Exception):
        t.call('brain_mouse_scan_origin', {'action': 'select', 'origin': 'bogus'})
    with pytest.raises(Exception):
        t.call('brain_mouse_scan_origin', {'action': 'select'})
    assert t.call('brain_mouse_scan_origin', {})['status'] == 'NEEDS_USER_CHOICE'


def test_inspect_inputs_carries_hint(tmp_path):
    (tmp_path / 'a.txt').write_text('x')
    t = T(tmp_path)
    assert t.call('brain_mouse_inspect_inputs', {'relative_paths': ['a.txt']})['scan_origin']['status'] == 'NEEDS_USER_CHOICE'
    t.call('brain_mouse_scan_origin', {'action': 'select', 'origin': 'real_scan'})
    assert t.call('brain_mouse_inspect_inputs', {'relative_paths': ['a.txt']})['scan_origin']['origin'] == 'real_scan'


def test_recognize_shell_seam_failure_adds_next_hint(tmp_path, monkeypatch):
    from cadmcp_brain.studio import scan_shellparts

    def boom(*a, **k):
        raise BrainError('SHELL_SEAM_NOT_FOUND', 'No crease.', {'supported_columns': 0})
    monkeypatch.setattr(scan_shellparts, 'recognize_shell', boom)
    with pytest.raises(BrainError) as e:
        T(tmp_path).call('brain_mouse_recognize_shell', {'scan_id': 'x'})
    assert e.value.code == 'SHELL_SEAM_NOT_FOUND' and e.value.message == 'No crease.'
    assert e.value.details['supported_columns'] == 0 and 'brain_mouse_scan_origin' in e.value.details['next']
