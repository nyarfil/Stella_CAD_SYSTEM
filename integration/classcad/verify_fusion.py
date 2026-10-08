"""Run inside Fusion via its MCP: a new test document only, no saving."""
import hashlib
import json
from pathlib import Path
import adsk.core
import adsk.fusion

SOURCE = Path(r'E:\aiwork\Stella_CAD_SYSTEM\integration\classcad\verification\build-20261003\box.step')
REPORT = SOURCE.parent / 'fusion-measurements.json'

def run(_context: str):
    digest = hashlib.sha256(SOURCE.read_bytes()).hexdigest()
    app = adsk.core.Application.get()
    original = app.activeDocument
    original_name = original.name if original else None
    original_modified = original.isModified if original else None
    test = None
    try:
        options = app.importManager.createSTEPImportOptions(str(SOURCE))
        options.isViewFit = False
        test = app.importManager.importToNewDocument(options)
        if test is None:
            raise RuntimeError('STEP import did not create a test document.')
        test.name = 'STELLA_CLASSCAD_FUSION_PROBE_20261003'
        design = adsk.fusion.Design.cast(app.activeProduct)
        if design is None:
            raise RuntimeError('No Fusion Design in imported test document.')
        root = design.rootComponent
        bodies = [root.bRepBodies.item(i) for i in range(root.bRepBodies.count)]
        for occurrence in root.allOccurrences:
            bodies.extend(occurrence.bRepBodies.item(i) for i in range(occurrence.bRepBodies.count))
        bounds = root.preciseBoundingBox
        minimum = [bounds.minPoint.x * 10, bounds.minPoint.y * 10, bounds.minPoint.z * 10]
        maximum = [bounds.maxPoint.x * 10, bounds.maxPoint.y * 10, bounds.maxPoint.z * 10]
        extents = [b - a for a, b in zip(minimum, maximum)]
        volume = sum(body.physicalProperties.volume * 1000 for body in bodies)
        passed = (len(bodies) == 1 and all(body.isSolid for body in bodies)
                  and all(abs(a - b) <= 1e-6 for a, b in zip(extents, [20., 10., 5.]))
                  and abs(volume - 1000.) <= 1e-5)
        report = {'source_sha256': digest, 'test_document': test.name,
                  'source_unchanged': hashlib.sha256(SOURCE.read_bytes()).hexdigest() == digest,
                  'body_count': len(bodies), 'solid': all(body.isSolid for body in bodies),
                  'bounds_mm': minimum + maximum, 'extents_mm': extents,
                  'volume_mm3': volume, 'geometry_passed': passed,
                  'physical_performance': 'unknown', 'saved': False}
    finally:
        if original is not None:
            original.activate()
    report['original_document'] = original_name
    report['original_modified_state_preserved'] = original is None or original.isModified == original_modified
    report['original_active_restored'] = original is None or app.activeDocument == original
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False))
