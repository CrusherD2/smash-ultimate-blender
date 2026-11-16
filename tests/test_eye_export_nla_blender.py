from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace as NS
from unittest.mock import patch
import importlib

fixture = Path(__file__).with_name('test_addon_registration_blender.py')
exec(compile(fixture.read_text().split('addon_utils.disable(MODULE')[0], str(fixture), 'exec'))
bake = importlib.import_module(MODULE + '.source.extras.rig_export')
eye = importlib.import_module(MODULE + '.source.extras.eye_rig')
layers = importlib.import_module(MODULE + '.source.extras.visibility_layer')
compat = importlib.import_module(MODULE + '.source.blender_compat')
curves = importlib.import_module(MODULE + '.source.anim.fcurve_compat')
export = importlib.import_module(MODULE + '.source.anim.export_anim')
bpy.ops.object.armature_add()
obj = bpy.context.object
bpy.ops.object.mode_set(mode='EDIT')
obj.data.edit_bones[0].name = 'Hip'
ctrl = obj.data.edit_bones.new(eye.EYE_CTRL_BONE)
ctrl.head, ctrl.tail = (0, 0, 0), (0, 1, 0)
ctrl.use_deform = False
bpy.ops.object.mode_set(mode='OBJECT')
obj.animation_data_create()
compat.assign_action(obj.animation_data, bpy.data.actions.new('Base bones'))
for frame in (1, 3):
    obj.pose.bones['Hip'].keyframe_insert(data_path='location', frame=frame)
sap = obj.data.sub_anim_properties
for name in ('EyeL', 'EyeR'):
    track = sap.mat_tracks.add()
    track.name = name
    prop = track.properties.add()
    prop.name, prop.sub_type = eye.CV31, 'VECTOR'
obj.data.animation_data_create()
base = bpy.data.actions.new('Base SAP')
compat.assign_action(obj.data.animation_data, base)
for track in sap.mat_tracks:
    track.properties[0].custom_vector = (1, 1, 0, 0)
    obj.data.keyframe_insert(data_path=track.properties[0].path_from_id('custom_vector'), frame=1)
entry = sap.vis_track_entries.add()
entry.name = 'baseform_Angry'
overlay = bpy.data.actions.new('Visibility overlay')
compat.assign_action(obj.data.animation_data, overlay)
for frame in (1, 3):
    entry.value = False
    obj.data.keyframe_insert(data_path=entry.path_from_id('value'), frame=frame)
layers.install_layer(obj.data.animation_data, base, overlay, 1)
animation = obj.data.animation_data
assert animation.use_tweak_mode
original_action, original_slot = animation.action, animation.action_slot
original_bones = obj.animation_data.action
bpy.context.scene.frame_set(2, subframe=0.25)
bpy.context.scene.tool_settings.use_keyframe_insert_auto = True
original_tracks = [(track.name, track.mute, [(strip.action, strip.frame_start, strip.frame_end) for strip in track.strips])
                   for track in animation.nla_tracks]
original_count = len(bpy.data.actions)
original_curves = [(fc.data_path, fc.array_index, [tuple(k.co) for k in fc.keyframe_points])
                   for fc in curves.get_fcurves(base, 'ARMATURE')]

def restored():
    assert animation.use_tweak_mode
    assert animation.action == original_action and animation.action_slot == original_slot
    assert obj.animation_data.action == original_bones
    assert len(bpy.data.actions) == original_count
    assert bpy.context.scene.frame_current == 2 and bpy.context.scene.frame_subframe == 0.25
    assert bpy.context.scene.tool_settings.use_keyframe_insert_auto
    assert [(track.name, track.mute, [(strip.action, strip.frame_start, strip.frame_end) for strip in track.strips])
            for track in animation.nla_tracks] == original_tracks
    assert [(fc.data_path, fc.array_index, [tuple(k.co) for k in fc.keyframe_points])
            for fc in curves.get_fcurves(base, 'ARMATURE')] == original_curves

with patch.object(bake, 'needs_bake', return_value=True), \
     patch.object(eye, 'compute_cv31', side_effect=lambda *args: (
         0.2 * bpy.context.scene.frame_current, 0.3 * bpy.context.scene.frame_current,
         0.4 * bpy.context.scene.frame_current, None)):
    with bake.temporary_rig_bake(bpy.context, obj, 1, 3):
        assert not animation.use_tweak_mode
        assert animation.action != base
    restored()
    try:
        with bake.temporary_rig_bake(bpy.context, obj, 1, 3):
            raise RuntimeError('simulated export failure')
    except RuntimeError as error:
        assert str(error) == 'simulated export failure'
    else:
        raise AssertionError('Export exception was swallowed')
    restored()
    with TemporaryDirectory() as directory:
        path = str(Path(directory) / 'eye_export.nuanmb')
        export.export_model_anim_fast(bpy.context, NS(report=lambda *args: None), obj,
                                      path, True, True, True, 1, 3)
        result = addon.dependencies.ssbh_data_py.anim_data.read_anim(path)
        nodes = next(group.nodes for group in result.groups if group.group_type.name == 'Material')
        for node in nodes:
            values = next(track.values for track in node.tracks if track.name == eye.CV31)
            assert len(values) == 3
            for frame, value in enumerate(values, 1):
                assert abs(value[2] - frame * (0.2 if node.name == 'EyeL' else 0.3)) < 1e-5
                assert abs(value[3] - frame * 0.4) < 1e-5
    restored()
print('EYE EXPORT IN NATIVE NLA TWEAK MODE AND SUCCESS/FAILURE RESTORATION PASSED')
