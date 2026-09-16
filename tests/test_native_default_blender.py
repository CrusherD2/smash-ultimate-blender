"""The native backend's default must be explicit, overridable, and gated.

The default was flipped on the corpus evidence in
docs/benchmarks/native-default-2026-09-13.md: 28 runs over three fixtures and
two Blender versions all landed on the same solved pose as Blender's backend
-- the guards declined the hard near-straight chain-frames and Blender's own
search finished those, so this is proof of the shipped path's outcome, not of
the Rust solver reproducing Blender's arithmetic. See that doc for the full
account. What this test pins is the resolution rule around that decision, not
the numerics -- that an unset SUB_NATIVE_IK engages the backend where it is
supported and only where it is supported, and that an explicit '0' overrides
it on every platform.
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

# enabled() answers "native at all", verifying() answers "verify or not", and the
# two disagree in exactly one mode. ik_channels' pole-search gate pairs them, so
# pin the whole truth table rather than the diagonal -- in particular that
# verifying() is False under '0', which is safe there only because it is paired.
for value, want_enabled, want_verifying in (
        (None, True, False), ('experimental', True, False),
        ('1', True, True), ('0', False, False), ('', False, False)):
    os.environ.pop('SUB_NATIVE_IK', None)
    if value is not None:
        os.environ['SUB_NATIVE_IK'] = value
    assert ik_native.enabled() is want_enabled, f'enabled() wrong for {value!r}'
    assert ik_native.verifying() is want_verifying, f'verifying() wrong for {value!r}'

os.environ.pop('SUB_NATIVE_IK', None)

# The add-on preference is a user-facing off switch, but the environment
# variable is the documented escape hatch and the developer's verification
# tool -- every existing test above sets it, so it must keep winning over a
# saved preference or this whole suite would stop measuring what it claims to.
#
# The shared registration fixture enables the add-on with default_set=False,
# so bpy.context.preferences.addons[MODULE] is never populated here -- the
# same lookup addon_preferences.get_addon_preferences() already returns None
# for. That is itself the "lookup absent" case exercised below. To pin the
# "preference ticked/unticked" behaviour we stand in for a real preferences
# instance by monkeypatching get_addon_preferences(), the same helper the
# rest of the add-on uses to reach its own preferences.
addon_preferences = importlib.import_module(MODULE + '.source.addon_preferences')
_real_get_addon_preferences = addon_preferences.get_addon_preferences


class _FakePrefs:
    use_native_ik_accelerator = True


fake_prefs = _FakePrefs()
addon_preferences.get_addon_preferences = lambda context=None: fake_prefs

try:
    fake_prefs.use_native_ik_accelerator = True
    os.environ.pop('SUB_NATIVE_IK', None)
    assert ik_native.enabled() is True, 'preference enabled + unset env should engage the backend'

    fake_prefs.use_native_ik_accelerator = False
    os.environ.pop('SUB_NATIVE_IK', None)
    assert ik_native.enabled() is False, 'unticked preference + unset env should not engage the backend'

    fake_prefs.use_native_ik_accelerator = False
    os.environ['SUB_NATIVE_IK'] = '1'
    assert ik_native.enabled() is True, "explicit SUB_NATIVE_IK='1' must win over an unticked preference"

    fake_prefs.use_native_ik_accelerator = False
    os.environ['SUB_NATIVE_IK'] = 'experimental'
    assert ik_native.enabled() is True, "explicit SUB_NATIVE_IK='experimental' must win over an unticked preference"

    # A lookup that raises (background/headless quirks, registration
    # ordering, an unexpected module name) must be treated as enabled and
    # must never raise into a match.
    os.environ.pop('SUB_NATIVE_IK', None)

    def _raise(context=None):
        raise RuntimeError('boom')

    addon_preferences.get_addon_preferences = _raise
    assert ik_native.enabled() is True, 'a raising preference lookup must fall back to enabled'
finally:
    addon_preferences.get_addon_preferences = _real_get_addon_preferences

# The real lookup: this harness never populates preferences.addons[MODULE],
# so get_addon_preferences() genuinely returns None here -- pin that the
# absent-preferences case (not just a simulated exception) also resolves to
# enabled.
assert addon_preferences.get_addon_preferences() is None, \
    'expected this test harness to leave the add-on preferences unreachable'
os.environ.pop('SUB_NATIVE_IK', None)
assert ik_native.enabled() is True, 'an absent preferences instance must fall back to enabled'

os.environ.pop('SUB_NATIVE_IK', None)
print('NATIVE_DEFAULT_OK')
