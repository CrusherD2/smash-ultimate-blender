"""Older generated fade-driver expressions must not push a keyed match off the native path.

blender --background --factory-startup --python-exit-code 1 --python tests/test_ik_old_detail_driver_native_blender.py
"""
from pathlib import Path

fixture = Path(__file__).with_name('test_ik_detail_acceleration_blender.py')
exec(compile(fixture.read_text().split('\naudit()\nfor repeat')[0], str(fixture), 'exec'))
ik.match(bpy.context, obj, 'LEGS', _batch=True)
curves = [fc for fc in obj.animation_data.drivers if ik.PULL_BASE in fc.data_path]
assert curves
for curve in curves:
    # Format written by earlier releases; equivalent but not byte-identical.
    curve.driver.expression = 'min(1,' + curve.driver.expression + ')'
audit(False)
ik.match(bpy.context, obj, 'LEGS', _batch=True)
record = diag.record()
assert record['reasons'].get('selfcontained') == 'ok', record
assert record['counts'].get('native_solves', 0) == 32, record
audit()
print('OLD DETAIL DRIVER EXPRESSIONS ARE REWRITTEN BEFORE THE NATIVE AUDIT PASSED')
