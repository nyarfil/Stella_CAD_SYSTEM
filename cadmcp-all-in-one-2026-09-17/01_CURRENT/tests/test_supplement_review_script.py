"""No model calls: one-shot review runner output and attachment boundaries."""
from pathlib import Path

import pytest

import scripts.check_supplement_review as runner
from cadmcp_brain.req2cad.common import file_hash


def test_review_run_requires_new_isolated_output(tmp_path,monkeypatch):
    root=tmp_path/'verification';root.mkdir()
    monkeypatch.setattr(runner,'VERIFICATION_ROOT',root)
    assert runner.resolve_run_root(root/'new')==root/'new'
    for path in (root,tmp_path/'outside'):
        with pytest.raises(ValueError):runner.resolve_run_root(path)
    (root/'existing').mkdir()
    with pytest.raises(ValueError):runner.resolve_run_root(root/'existing')


def test_review_runner_requires_explicit_execution_flag():
    with pytest.raises(SystemExit) as caught:
        runner.main([])
    assert caught.value.code==2


def test_review_attachment_validation_rejects_missing_and_changed_evidence(tmp_path):
    attachments=[]
    for name in sorted(runner.EXPECTED_EVIDENCE|{'iso.png'}):
        path=tmp_path/name
        path.write_bytes(b'unit-test-only; not real image evidence')
        attachments.append({'path':str(path),'sha256':file_hash(path),
                            'kind':'image' if name.endswith('.png') else 'json'})
    packet={'subject':{'payload':{'evidence_attachments':attachments}}}
    assert runner.validate_attachments(packet,tmp_path)==attachments
    missing={'subject':{'payload':{'evidence_attachments':attachments[:-1]}}}
    with pytest.raises(RuntimeError,match='omitted'):
        runner.validate_attachments(missing,tmp_path)
    Path(attachments[0]['path']).write_bytes(b'changed')
    with pytest.raises(RuntimeError,match='hash-mismatched'):
        runner.validate_attachments(packet,tmp_path)
