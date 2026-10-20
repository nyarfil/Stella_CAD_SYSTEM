"""brain_mouse_scan_origin: the USER decides where a scan comes from (real_scan | fused_original); the choice picks the pipeline.

Modelled on brain_mesh_backend: saved inside this workspace only (<workspace>/.cadmcp/scan-origin.json), NEEDS_USER_CHOICE while
unset, nothing is chosen automatically. Guidance only: no existing tool changes its behaviour because of this choice.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from ..errors import BrainError
from ..req2cad.common import atomic_json, json_load

SELECTION_FILE = '.cadmcp/scan-origin.json'
Origin = Literal['real_scan', 'fused_original']
QUESTION_EN = "Is this an existing real mouse's 3D scan, or an original model made by blending mice (findmymouse fusion)?"
QUESTION_JA = 'これは実在するマウスの3Dスキャンですか？それとも findmymouse で複数のマウスを融合して作ったオリジナルモデルですか？'

ORIGINS: dict[str, dict[str, Any]] = {
    'real_scan': {
        'means_en': 'A 3D scan of a REAL existing mouse (with photos): parting seam grooves, click grooves and the bottom-plate split physically exist in the mesh.',
        'means_ja': '実在するマウスの3Dスキャン（写真あり）。分割シーム溝・クリック溝・ボトムプレート分割がメッシュに実在する。',
        'pipeline': [
            {'tool': 'brain_mouse_prepare_scan', 'implemented': True}, {'tool': 'brain_mouse_scan_clean', 'implemented': True},
            {'tool': 'brain_mouse_recognize_regions', 'implemented': True}, {'tool': 'brain_mouse_recognize_shell', 'implemented': True},
            {'tool': 'brain_mouse_scan_flush', 'implemented': True}, {'tool': 'brain_mouse_scan_symmetrise', 'implemented': True},
            {'tool': 'brain_mouse_shell_fit', 'implemented': True}, {'tool': 'brain_mouse_shell_solid', 'implemented': True},
            {'tool': 'brain_mouse_click_slots', 'implemented': True}, {'tool': 'brain_mouse_plate_side', 'implemented': True}],
    },
    'fused_original': {
        'means_en': 'An ORIGINAL model that does not exist (mouse A x mouse B blended on findmymouse): no parting seam, no click grooves, no bottom-plate split; dirty (ripples, facets, dents). recognize_shell fails with SHELL_SEAM_NOT_FOUND and labels are unavailable.',
        'means_ja': '実在しないオリジナルモデル（findmymouse でマウスA×Bを融合）。分割シーム・クリック溝・ボトムプレート分割が無く、表面が荒れている（波打ち・ファセット・凹み）。recognize_shell は SHELL_SEAM_NOT_FOUND で失敗し、ラベルは使えない。',
        'pipeline': [
            {'tool': 'brain_mouse_prepare_scan', 'implemented': True},
            {'tool': 'brain_mouse_scan_fair', 'implemented': True, 'note': 'label-free band-stop fairing'},
            {'tool': 'geometry-only inference of the bottom plate', 'implemented': False},
            {'tool': 'geometry-only inference of the click regions', 'implemented': False},
            {'tool': 'merge into the real_scan pipeline from brain_mouse_scan_flush on', 'implemented': False}],
    },
}


def _sel_path(ws: Path) -> Path:
    return Path(ws) / SELECTION_FILE


def read_selection(ws: Path) -> dict[str, Any] | None:
    p = _sel_path(ws)
    if not p.is_file():
        return None
    try:
        sel = json_load(p).get('selection')
    except Exception:  # noqa: BLE001 - an unreadable file is treated as no choice
        return None
    return sel if isinstance(sel, dict) and sel.get('origin') in ORIGINS else None


def hint(ws: Path) -> dict[str, Any]:
    """Short block for guidance tools: current choice, or NEEDS_USER_CHOICE with the question."""
    sel = read_selection(ws)
    if sel:
        return {'status': 'SELECTED', 'origin': sel['origin'], 'pipeline': [s['tool'] for s in ORIGINS[sel['origin']]['pipeline'] if s['implemented']],
                'tool': 'brain_mouse_scan_origin'}
    return {'status': 'NEEDS_USER_CHOICE', 'ask_user_first': True, 'question_en': QUESTION_EN, 'question_ja': QUESTION_JA,
            'options': list(ORIGINS), 'tool': 'brain_mouse_scan_origin', 'automatic_choice': False}


def scan_origin(ws: Path, action: str, origin: str | None, reason: str | None) -> dict[str, Any]:
    if action not in ('status', 'select', 'clear'):
        raise BrainError('SCAN_ORIGIN_ARGUMENT', "action must be 'status', 'select' or 'clear'.", {'given': action})
    if action == 'select':
        if origin not in ORIGINS:
            raise BrainError('SCAN_ORIGIN_ARGUMENT', f'select needs origin one of {sorted(ORIGINS)}.', {'given': origin})
        atomic_json(_sel_path(ws), {'schema': 'cadmcp.scan_origin_selection/1', 'selection': {
            'origin': origin, 'set_utc': datetime.now(timezone.utc).isoformat(timespec='seconds'), 'reason': (reason or '')[:500]}})
    elif action == 'clear':
        _sel_path(ws).unlink(missing_ok=True)
    sel = read_selection(ws)
    out: dict[str, Any] = {'schema': 'scan_origin_status/1', 'selection_file': SELECTION_FILE, 'scope': 'this workspace only',
                           'status': 'SELECTED' if sel else 'NEEDS_USER_CHOICE', 'selection': sel, 'automatic_choice': False,
                           'origins': ORIGINS,
                           'how_to_set': "brain_mouse_scan_origin(action='select', origin=<real_scan|fused_original>) after the user answered"}
    if not sel:
        out.update({'question_en': QUESTION_EN, 'question_ja': QUESTION_JA})
    else:
        out['active_pipeline'] = ORIGINS[sel['origin']]['pipeline']
    return out


class ScanOriginToolsMixin:
    def brain_mouse_scan_origin(self, action: Literal['status', 'select', 'clear'] = 'status', origin: Origin | None = None, reason: str | None = None) -> dict[str, Any]:
        """FIRST QUESTION for a mouse scan, decided by the USER (never automatically): is the input a 3D scan of a REAL existing mouse ('real_scan': seam grooves, click grooves and bottom-plate split exist; pipeline prepare_scan, scan_clean, recognize_regions, recognize_shell, scan_flush, scan_symmetrise, shell_fit, shell_solid, click_slots, plate_side) or an ORIGINAL model blended from mice on findmymouse ('fused_original': no seam, no click grooves, no plate split, dirty surface; pipeline prepare_scan, scan_fair, then geometry-only bottom-plate / click-region inference which is NOT implemented yet, then merge into the real_scan pipeline)? Saved in THIS workspace only (.cadmcp/scan-origin.json). action 'status' (read-only) lists both origins with meaning, ordered pipeline with implemented / not-yet-implemented stages, and the current choice or NEEDS_USER_CHOICE with the question (English + Japanese) to ask the user; 'select' needs origin (optional reason); 'clear' removes the choice. Guidance only: no other tool changes behaviour because of this choice."""
        return scan_origin(self.brain.store.root, action, origin, reason)
