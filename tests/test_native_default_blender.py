"""The native backend's default must be explicit, overridable, and gated.

The default was flipped on the corpus evidence in
docs/benchmarks/native-default-2026-09-13.md: 28 runs over three fixtures and
two Blender versions, every one bit-identical to Blender's backend, with the
guards declining nothing. What this test pins is the resolution rule around
that decision, not the numerics -- that an unset SUB_NATIVE_IK engages the
backend where it is supported and only where it is supported, and that an
explicit '0' overrides it on every platform.
"""
from pathlib import Path
import importlib, os, sys

fixture = Path(__file__).with_name('test_addon_registration_blender.py')
exec(compile(fixture.read_text().split('addon_utils.disable(MODULE')[0], str(fixture), 'exec'))
ik_native = importlib.import_module(MODULE + '.source.extras.ik_native')

for key in ('SUB_NATIVE_IK',):
    os.environ.pop(key, None)

supported = (sys.platform == 'win32' and bpy.app.version[:2] in {(4, 5), (5, 2)}
             and (ROOT / 'native/bin/sub_ik_match_native.dll').is_file())

factory = ik_native.get_factory()
if supported:
    assert factory is not None, 'native backend did not engage by default on a supported platform'
    factory.close()
else:
    assert factory is None, 'native backend engaged on an unsupported platform'

# An explicit off must always win, on every platform.
os.environ['SUB_NATIVE_IK'] = '0'
assert ik_native.get_factory() is None, 'SUB_NATIVE_IK=0 did not force the native backend off'

# Verification mode stays reachable and stays verifying: '1' engages the
# backend where it is supported, and unlike the new default it must not skip
# the per-candidate comparison against Blender.
os.environ['SUB_NATIVE_IK'] = '1'
factory = ik_native.get_factory()
assert (factory is not None) == supported, 'SUB_NATIVE_IK=1 no longer resolves to verification mode'
if factory is not None:
    factory.close()
assert ik_native.verifying(), 'SUB_NATIVE_IK=1 stopped verifying candidates against Blender'

# The adopted default and the explicit force-on both skip verification.
for value in (None, 'experimental'):
    os.environ.pop('SUB_NATIVE_IK', None)
    if value is not None:
        os.environ['SUB_NATIVE_IK'] = value
    assert not ik_native.verifying(), f'SUB_NATIVE_IK={value!r} unexpectedly verifies'

os.environ.pop('SUB_NATIVE_IK', None)
print('NATIVE_DEFAULT_OK')
