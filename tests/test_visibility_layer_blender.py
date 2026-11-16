from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch
import importlib

fixture = Path(__file__).with_name('test_addon_registration_blender.py')
exec(compile(fixture.read_text().split('addon_utils.disable(MODULE')[0], str(fixture), 'exec'))
imp = importlib.import_module(MODULE + '.source.anim.import_anim')
compat = importlib.import_module(MODULE + '.source.blender_compat')
curves = importlib.import_module(MODULE + '.source.anim.fcurve_compat')
layers = importlib.import_module(MODULE + '.source.extras.visibility_layer')
arma = bpy.data.objects.new('LayerTest', bpy.data.armatures.new('LayerTest'))
bpy.context.collection.objects.link(arma)
bpy.context.view_layer.objects.active = arma
arma.select_set(True)
arma.animation_data_create()
arma.data.animation_data_create()
bone = bpy.data.actions.new('Base bones')
compat.assign_action(arma.animation_data, bone)
sap = arma.data.sub_anim_properties
for name in ('baseform_angry', 'untouched'):
    entry = sap.vis_track_entries.add()
    entry.name = name
base = bpy.data.actions.new('Regular SAP')
compat.assign_action(arma.data.animation_data, base)
for index in range(2):
    path = f'sub_anim_properties.vis_track_entries[{index}].value'
    for frame in (1, 10):
        sap.vis_track_entries[index].value = True
        arma.data.keyframe_insert(data_path=path, frame=frame)
mat = sap.mat_tracks.add()
mat.name = 'Face'
prop = mat.properties.add()
prop.name, prop.sub_type = 'CustomFloat0', 'FLOAT'
for frame in (1, 10):
    prop.custom_float = 0.25
    arma.data.keyframe_insert(data_path=prop.path_from_id('custom_float'), frame=frame)
original = [(f.data_path, [tuple(k.co) for k in f.keyframe_points]) for f in curves.get_fcurves(base, 'ARMATURE')]
groups = [NS(group_type=NS(name='Visibility'), nodes=[NS(name='baseform_angry', tracks=[NS(values=[False, True])])]),
          NS(group_type=NS(name='Material'), nodes=[NS(name='Face', tracks=[NS(name='CustomFloat0', values=[0.75, 0.9])])])]
scene = bpy.context.scene
scene.frame_start, scene.frame_end = 1, 80
with patch.object(imp.ssbh_data_py.anim_data, 'read_anim', return_value=NS(final_frame_index=1, groups=groups)):
    assert bpy.ops.sub.import_visibility_layer(filepath='a00transformbase.nuanmb') == {'FINISHED'}
assert arma.animation_data.action == bone
assert (scene.frame_start, scene.frame_end) == (1, 80)
assert original == [(f.data_path, [tuple(k.co) for k in f.keyframe_points]) for f in curves.get_fcurves(base, 'ARMATURE')]
assert len(arma.data.animation_data.nla_tracks) == 2
scene.frame_set(1)
assert not sap.vis_track_entries[0].value
assert sap.vis_track_entries[1].value
assert abs(prop.custom_float - 0.75) < 0.001
scene.frame_set(2)
assert sap.vis_track_entries[0].value
assert abs(prop.custom_float - 0.9) < 0.001
layer = arma.data.animation_data.nla_tracks[-1]
layer.mute = True
scene.frame_set(1)
assert sap.vis_track_entries[0].value
assert abs(prop.custom_float - 0.25) < 0.001
layer.mute = False
scene.frame_set(1)
assert not sap.vis_track_entries[0].value
print('VISIBILITY LAYER OVERRIDE, ISOLATION, MATERIAL AND MUTE TEST PASSED')
# Replacing the regular animation keeps the overlay independent and above it.
with patch.object(imp.ssbh_data_py.anim_data, 'read_anim', return_value=NS(final_frame_index=9, groups=groups)):
    imp._import_model_anim(bpy.context, 'a00wait2.nuanmb', False, True, True, 1, arma)
assert arma.data.animation_data.action == arma.data.animation_data.nla_tracks.get(layers.BASE_TRACK).strips[0].action
assert arma.data.animation_data.nla_tracks[-1] == layer
assert arma.data.animation_data.nla_tracks.get(layers.BASE_TRACK).strips[0].action != base
scene.frame_set(1)
assert not sap.vis_track_entries[0].value
assert original == [(f.data_path, [tuple(k.co) for k in f.keyframe_points]) for f in curves.get_fcurves(base, 'ARMATURE')]
print('REGULAR ANIMATION REIMPORT PRESERVES VISIBILITY LAYER TEST PASSED')
# The folder browser shares the importer's selection but imports only layers.
ssp = scene.sub_scene_properties
ssp.animation_import_files.clear()
for name, selected in (('a00layer_b', True), ('a00skip', False), ('a00layer_a', True)):
    item = ssp.animation_import_files.add()
    item.name, item.path, item.selected = name, name + '.nuanmb', selected
before = len(arma.data.animation_data.nla_tracks)
regular_bones = arma.animation_data.action
with patch.object(imp.ssbh_data_py.anim_data, 'read_anim', return_value=NS(final_frame_index=1, groups=groups)):
    assert bpy.ops.sub.import_visibility_folder() == {'FINISHED'}
assert len(arma.data.animation_data.nla_tracks) == before + 2
assert arma.animation_data.action == regular_bones
assert [item.selected for item in ssp.animation_import_files] == [True, False, True]
with patch.object(imp.ssbh_data_py.anim_data, 'read_anim', return_value=NS(final_frame_index=1, groups=groups)):
    assert bpy.ops.sub.import_visibility_folder(import_all=True) == {'FINISHED'}
assert len(arma.data.animation_data.nla_tracks) == before + 5
print('SHARED FOLDER SELECTED AND ALL VISIBILITY LAYER IMPORT TEST PASSED')
# Keyed base edits remain editable without taking precedence over the layer.
scene.frame_set(1)
editable = arma.data.animation_data.action
assert editable == arma.data.animation_data.nla_tracks.get(layers.BASE_TRACK).strips[0].action
sap.vis_track_entries[0].value = True
assert layers.keyframe_base_property(arma.data, data_path='sub_anim_properties.vis_track_entries[0].value', frame=1)
prop.custom_float = 0.1
assert layers.keyframe_base_property(arma.data, data_path=prop.path_from_id('custom_float'), frame=1)
layers.refresh_visibility_layers()
bpy.context.view_layer.update()
assert not sap.vis_track_entries[0].value
assert abs(prop.custom_float - 0.75) < 0.001
assert curves.find_fcurve(editable, 'sub_anim_properties.vis_track_entries[0].value', id_type='ARMATURE').evaluate(1) == 1
for track in arma.data.animation_data.nla_tracks:
    if track.name.startswith(layers.LAYER_PREFIX):
        track.mute = True
scene.frame_set(1)
assert sap.vis_track_entries[0].value
assert abs(prop.custom_float - 0.1) < 0.001
# FaceN replaces full expressions whose track names contain no facial-part hint.
face = importlib.import_module(MODULE + '.source.extras.face_picker')
arma = bpy.data.objects.new('FaceNTest', bpy.data.armatures.new('FaceNTest'))
bpy.context.collection.objects.link(arma)
bpy.context.view_layer.update()
sap = arma.data.sub_anim_properties
picker = face.get_picker(arma)
picker.insert_keyframes = False
for name in ('baseform_FaceN', 'baseform_Raging', 'baseform_Hurt1'):
    entry = sap.vis_track_entries.add()
    entry.name = name
    expression = picker.expressions.add()
    expression.expression_id = name
    expression.name = name
    face.set_expression_vis_data(expression, [name])
for expression in (picker.expressions[1], picker.expressions[0], picker.expressions[2], picker.expressions[0]):
    face.apply_vis_expression(bpy.context, arma, expression)
    enabled = [entry.name for entry in sap.vis_track_entries if entry.value and entry.name.startswith('baseform_')]
    assert enabled == [expression.name], enabled
print('EDITED BASE REMAINS BELOW LAYERS AND FACEN CLEARS FULL EXPRESSIONS TEST PASSED')
# Native upper-stack evaluation works even with Auto Key on and no frame handlers.
from time import perf_counter
layer_arma = bpy.data.objects.get('LayerTest')
animation = layer_arma.data.animation_data
assert animation.use_tweak_mode
assert animation.action_influence == 1
for track in animation.nla_tracks:
    if track.name.startswith(layers.LAYER_PREFIX):
        track.mute = False
for handlers in (bpy.app.handlers.frame_change_pre, bpy.app.handlers.frame_change_post,
                 bpy.app.handlers.animation_playback_pre, bpy.app.handlers.animation_playback_post):
    assert not any(callback.__module__ == layers.__name__ for callback in handlers)
for auto_key in (False, True):
    scene.tool_settings.use_keyframe_insert_auto = auto_key
    with patch.object(layers, 'is_playing_animation', return_value=True):
        start = perf_counter()
        for frame in range(120):
            scene.frame_set(1 + frame % 2)
            assert layer_arma.data.sub_anim_properties.vis_track_entries[0].value == (frame % 2 == 1)
            expected = 0.75 if frame % 2 == 0 else 0.9
            assert abs(layer_arma.data.sub_anim_properties.mat_tracks[0].properties[0].custom_float - expected) < 0.001
        elapsed = perf_counter() - start
    print(f'Native NLA playback, Auto Key={auto_key}: 120 synthetic frames in {elapsed:.3f}s')
scene.tool_settings.use_keyframe_insert_auto = False
layers.restore_native_layers()
assert animation.use_tweak_mode
scene.frame_set(1)
assert not layer_arma.data.sub_anim_properties.vis_track_entries[0].value
print('NATIVE NLA BASE EDITING, UPPER STACK, AUTO KEY AND RESTORE TEST PASSED')
