"""Regression coverage for intermediate IK bones, matching, export and bulk bake."""
from pathlib import Path
import importlib
import tempfile
from types import SimpleNamespace
from mathutils import Matrix
fixture = Path(__file__).with_name('test_addon_registration_blender.py')
exec(compile(fixture.read_text().split('addon_utils.disable(MODULE')[0], str(fixture), 'exec'))
ik = importlib.import_module(MODULE + '.source.extras.ik_channels')
apply = importlib.import_module(MODULE + '.source.extras.apply_ik_animation')
rig = importlib.import_module(MODULE + '.source.extras.create_animation_rig')
curves = importlib.import_module(MODULE + '.source.anim.fcurve_compat')
export = importlib.import_module(MODULE + '.source.anim.export_anim')
bulk = importlib.import_module(MODULE + '.source.extras.bulk_ik')

bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete(use_global=False)
data = bpy.data.armatures.new('Intermediate chain')
obj = bpy.data.objects.new('Intermediate chain', data)
bpy.context.collection.objects.link(obj)
bpy.context.view_layer.objects.active = obj
obj.select_set(True)
bpy.ops.object.mode_set(mode='EDIT')
path = ['ShoulderL', 'UpperTwistL', 'ArmL', 'LowerTwistL', 'HandL']
parent = data.edit_bones.new('Trans')
parent.head, parent.tail = (0, 0, 0), (0, 1, 0)
for index, name in enumerate(path):
    pb = data.edit_bones.new(name)
    pb.head = (0.15 * index * index, index + 1, 0)
    pb.tail = (0.15 * (index+1)**2, index + 2, 0)
    pb.parent = parent
    parent = pb
bpy.ops.object.mode_set(mode='POSE')
scene = bpy.context.scene
scene.frame_start, scene.frame_end = 1, 5
for frame in range(1, 6):
    scene.frame_set(frame)
    for index, name in enumerate(path):
        pb = obj.pose.bones[name]
        pb.rotation_mode = 'XYZ'
        pb.rotation_euler = (0.04*frame*(index+1), 0.025*frame, -0.02*frame*index)
        pb.location = (0.03*frame, 0.02*index*frame, 0)
        pb.scale = (1+0.01*frame,)*3
        for prop in ('location','rotation_euler','scale'):
            pb.keyframe_insert(prop, frame=frame)

def capture():
    result = {}
    for frame in range(1,6):
        scene.frame_set(frame)
        bpy.context.view_layer.update()
        result[frame] = {n:obj.pose.bones[n].matrix.copy() for n in path}
    return result

def compare(a,b,label,tol=0.0003):
    error = max(abs(a[f][n][i][j]-b[f][n][i][j]) for f in a for n in path for i in range(4) for j in range(4))
    print(label, error)
    assert error < tol, (label,error)

fk = capture()
ik.create_controls(bpy.context, obj, 'ARMS')
assert obj.pose.bones['HandIKL'].custom_shape is None
assert obj.pose.bones['ArmIKL'].custom_shape is None
ik.match(bpy.context, obj, 'ARMS', entire=True)
rig._set_ik_enabled(bpy.context,obj,True,'ARMS')
matched = capture()
compare(fk,matched,'match fidelity')
assert set(path) <= set(apply.collect_fk_bone_names(obj))
# Full IK hides all original path bones; fractional blends show both sets.
rig._set_ik_enabled(bpy.context,obj,True,'ARMS')
rig._sync_ik_fk_visibility(scene)
assert all(data.bones[n].hide for n in path)
assert not data.bones['HandIKL'].hide
# Keyed switches must update visibility when scrubbing.
for frame, factor in ((1,0.0),(2,0.5),(3,1.0)):
    data.sub_use_ik_arms = factor
    data.keyframe_insert('sub_use_ik_arms',frame=frame)
scene.frame_set(1)
assert not data.bones['ArmL'].hide and data.bones['HandIKL'].hide
scene.frame_set(2)
assert not data.bones['ArmL'].hide and not data.bones['HandIKL'].hide
scene.frame_set(3)
assert data.bones['ArmL'].hide and not data.bones['HandIKL'].hide
for fc in list(curves.get_all_action_fcurves(data.animation_data.action)):
    if fc.data_path == 'sub_use_ik_arms':
        curves.remove_fcurve(data.animation_data.action,fc)
data.sub_use_ik_arms = 1.0

# Scaling the target progressively changes intermediate output scales.
scene.frame_set(3)
control = obj.pose.bones['HandIKL']
control.scale = (2.0,)*3
bpy.context.view_layer.update()
base_scales = [obj.pose.bones[n].matrix.to_scale().x for n in path]
data.sub_ik_progressive_scale_arms = 1.0
bpy.context.view_layer.update()
scales = [obj.pose.bones[n].matrix.to_scale().x for n in path]
assert abs(scales[0]-base_scales[0]) < 1e-4
assert scales[1] > base_scales[1] and scales[2] > scales[1] and scales[3] > scales[2], scales
data.sub_ik_progressive_scale_arms = 0.0
scene.frame_set(3)

# Buttons key contact state, including the initial unplanted interval.
floor = importlib.import_module(MODULE + '.source.extras.ik_floor_contact')
floor.setup_limb(bpy.context,obj,'HandIKL','ARMS')
obj.sub_floor_contact.calibrating = False
limb = obj.sub_floor_contact.limbs[0]
scene.frame_set(2)
assert bpy.ops.sub.floor_contact(action='PLANT',control='HandIKL') == {'FINISHED'}
scene.frame_set(4)
assert bpy.ops.sub.floor_contact(action='RELEASE',control='HandIKL') == {'FINISHED'}
for frame, expected in ((1,False),(2,True),(3,True),(4,False),(2,True)):
    scene.frame_set(frame)
    assert limb.planted == expected, (frame,limb.planted)
floor.remove(bpy.context,obj)
matched = capture()

# Delete and reset original FK channels: independent playback must not change.
action = obj.animation_data.action
for fc in list(curves.get_all_action_fcurves(action, id_type='OBJECT')):
    if any(fc.data_path.startswith(obj.pose.bones[n].path_from_id()+'.') for n in path):
        curves.remove_fcurve(action,fc,id_type='OBJECT')
for n in path:
    obj.pose.bones[n].matrix_basis = Matrix.Identity(4)
compare(matched,capture(),'FK independence')
# Export a temporary bake and restore the live action and output mutes.
original = obj.animation_data.action
mutes = [c.mute for pb in obj.pose.bones for c in pb.constraints]
with tempfile.TemporaryDirectory() as directory:
    file = str(Path(directory)/'ik.nuanmb')
    reporter = SimpleNamespace(report=lambda *args, **kwargs: None)
    export.export_model_anim_fast(bpy.context,reporter,obj,file,True,False,False,1,5)
    assert Path(file).is_file()
    from_data = addon.dependencies.ssbh_data_py.anim_data.read_anim(file)
    import json
    pose = {}
    for group in from_data.groups:
        if group.group_type.name != 'Transform':
            continue
        for node in group.nodes:
            value = node.tracks[0].values[0]
            pose[node.name] = dict(translation=list(value.translation), rotation=list(value.rotation), scale=list(value.scale))
    assert pose
    assert set(pose).isdisjoint({'HandIKL', 'ArmIKL'})
    assert not any(n.startswith('BL_') for n in pose)
    idle = importlib.import_module(MODULE + '.source.extras.idle_pose_library')
    scene.frame_set(3)
    data.sub_use_ik_arms = 0.0
    result, message = idle.apply_pose_with_options(bpy.context,json.dumps(pose),ik_enabled=False)
    assert result == {'FINISHED'}, message
    expected_idle = {n:obj.pose.bones[n].matrix.copy() for n in path}
    data.sub_use_ik_arms = 1.0
    result, message = idle.apply_pose_with_options(bpy.context,json.dumps(pose),ik_enabled=True)
    assert result == {'FINISHED'}, message
    actual_idle = {n:obj.pose.bones[n].matrix.copy() for n in path}
    compare({3:expected_idle},{3:actual_idle},'idle pose IK match')
    matched = capture()
assert obj.animation_data.action == original
assert mutes == [c.mute for pb in obj.pose.bones for c in pb.constraints]
compare(matched,capture(),'export preserves live IK')
# Closing a suspended exporter must restore the temporary action and constraints.
iterator = export.export_model_anim_fast_steps(bpy.context,reporter,obj,
    str(Path(tempfile.gettempdir())/'sub_cancelled_ik_export.nuanmb'),True,False,False,1,5)
next(iterator)
assert obj.animation_data.action != original
iterator.close()
assert obj.animation_data.action == original
assert mutes == [c.mute for pb in obj.pose.bones for c in pb.constraints]
compare(matched,capture(),'cancelled export preserves IK')
# The regular bake and bulk bake must key identical FK channels.
with apply.temporary_export_bake(bpy.context,obj,1,5):
    regular_curves = {(fc.data_path,fc.array_index): [fc.evaluate(f) for f in range(1,6)]
        for fc in curves.get_all_action_fcurves(obj.animation_data.action,id_type='OBJECT')
        if any(fc.data_path.startswith(obj.pose.bones[n].path_from_id()+'.') for n in path)}
# Give two clips different IK edits and compare the bulk operator to viewport.
a = original
b = a.copy()
b.name = 'Second IK clip'
from_compat = importlib.import_module(MODULE + '.source.blender_compat')
from_compat.assign_action(obj.animation_data,b)
for fc in curves.get_all_action_fcurves(b,id_type='OBJECT'):
    if fc.data_path == obj.pose.bones['HandIKL'].path_from_id()+'.location' and fc.array_index == 0:
        for key in fc.keyframe_points:
            key.co.y += .25
        fc.update()
sap_a = data.animation_data.action
sap_b = bpy.data.actions.new(f'{obj.name} {b.name} SAP Data')
from_compat.assign_action(data.animation_data,sap_b)
data.sub_use_ik_arms = 0.35
for frame in (1,5):
    data.keyframe_insert('sub_use_ik_arms',frame=frame)
reference_b = capture()
from_compat.assign_action(obj.animation_data,a)
from_compat.assign_action(data.animation_data,sap_a)
reference_a = capture()
bulk.get_armature_actions = lambda obj: [a,b]
# Manual action ranges and unrelated timeline ranges must not crop either clip.
for clip in (a, b):
    clip.use_frame_range = True
    clip.frame_start, clip.frame_end = 2, 3
scene.frame_start, scene.frame_end = 40, 45
assert bpy.ops.sub.bulk_ik_bake_all('EXEC_DEFAULT') == {'FINISHED'}
assert (scene.frame_start, scene.frame_end) == (40, 45)
assert 'HandIKL' not in obj.pose.bones
from_compat.assign_action(obj.animation_data,a)
compare(reference_a,capture(),'bulk first clip')
for fc in curves.get_all_action_fcurves(a,id_type='OBJECT'):
    expected = regular_curves.get((fc.data_path,fc.array_index))
    if expected:
        assert max(abs(fc.evaluate(f)-expected[f-1]) for f in range(1,6)) < 1e-5
from_compat.assign_action(obj.animation_data,b)
compare(reference_b,capture(),'bulk second clip')
assert all(not data.bones[n].hide for n in path)
print('IK WORKFLOW REGRESSIONS PASSED')
