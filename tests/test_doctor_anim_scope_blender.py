"""The animation preflight must inspect exactly the actions being exported.

A problem in an animation the user did not select for export must never cancel
the export. Run with Blender --background --factory-startup --python-exit-code 1
--python this_file.
"""
from pathlib import Path
fixture = Path(__file__).with_name('test_addon_registration_blender.py')
exec(compile(fixture.read_text(encoding='utf-8').split('addon_utils.disable(MODULE')[0], str(fixture), 'exec'))

from types import SimpleNamespace

core = importlib.import_module(MODULE + '.source.doctor.core')
ui = importlib.import_module(MODULE + '.source.doctor.ui')
fcurve_compat = importlib.import_module(MODULE + '.source.anim.fcurve_compat')

bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete(use_global=False)
bpy.ops.object.armature_add()
armature = bpy.context.object
armature.name = 'AnimArmature'
bpy.context.view_layer.objects.active = armature


def make_action(name, frame=1.0):
    action = bpy.data.actions.new(name)
    fcurve = fcurve_compat.new_fcurve(action, 'location', index=0)
    keyframe = fcurve.keyframe_points.insert(frame, 0.0)
    return action, keyframe


good, _good_key = make_action('GoodAction')
bad, bad_key = make_action('BadAction')
# A non-finite keyframe is a blocking nan_transforms finding.
bad_key.co[0] = float('nan')


def nan_results(actions):
    return [
        result for result in core.run_checks(bpy.context, (core.SCOPE_ANIM,), actions=actions)
        if result.check_id == 'nan_transforms'
    ]


# Only the actions passed in are in scope.
assert not nan_results([good]), nan_results([good])
scoped = nan_results([good, bad])
assert len(scoped) == 1 and scoped[0].sub_target == 'BadAction', scoped
assert scoped[0].blocking, scoped[0]

# Both actions really are in the file, so the default scan still sees them.
assert core.DoctorScene(bpy.context, ('ANIM',), [good]).actions == [(armature, good)]
default_names = {
    action.name for _owner, action in core.DoctorScene(bpy.context, ('ANIM',)).actions
}
assert {'GoodAction', 'BadAction'} <= default_names, default_names

# Preflight follows the explicit export set.
state = bpy.context.scene.sub_doctor
state.run_before_export = True
state.block_on_errors = True
reporter = SimpleNamespace(report=lambda level, message: None)
assert ui.preflight(bpy.context, reporter, 'ANIM', actions=[good]) is True
assert ui.preflight(bpy.context, reporter, 'ANIM', actions=[bad]) is False

print('DOCTOR ANIM SCOPE PASSED')
profile.cleanup()
