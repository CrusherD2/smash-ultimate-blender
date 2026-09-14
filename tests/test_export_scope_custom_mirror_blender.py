from pathlib import Path
fixture = Path(__file__).with_name('test_addon_registration_blender.py')
exec(compile(fixture.read_text(encoding='utf-8').split('addon_utils.disable(MODULE')[0], str(fixture), 'exec'))
from mathutils import Matrix
from types import SimpleNamespace
core = importlib.import_module(MODULE + '.source.doctor.core')
ui = importlib.import_module(MODULE + '.source.doctor.ui')
flip = importlib.import_module(MODULE + '.source.extras.anim_flip')
mirror = importlib.import_module(MODULE + '.source.extras.mirror_animation')

bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete(use_global=False)
bpy.ops.object.armature_add()
obj = bpy.context.object
obj.name = 'Animation rig'
bpy.ops.object.mode_set(mode='EDIT')
obj.data.edit_bones.remove(obj.data.edit_bones[0])
for name, pos, roll in [('Trans',(0,0,0),0), ('Accessory.L',(1,-2,3),.4), ('Accessory.R',(1,2,3),-.7), ('Ribbon',(0,0,4),.2), ('Only.Left',(0,-3,1),0), ('Only.Right',(0,3,1),0)]:
    bone = obj.data.edit_bones.new(name)
    bone.head = pos
    bone.tail = (pos[0],pos[1],pos[2]+1)
    bone.roll = roll
bpy.ops.object.mode_set(mode='POSE')
# A stale model selection outside the current view layer must not affect ANIM.
model = bpy.data.objects.new('Remembered model', bpy.data.armatures.new('Model'))
ssp = bpy.context.scene.sub_scene_properties
ssp.model_export_arma = model
ssp.vanilla_update_prc = str(Path(profile.name)/'missing_update.prc')
ssp.vanilla_nusktb = str(Path(profile.name)/'missing.nusktb')
ssp.vanilla_flip_prc = str(Path(profile.name)/'missing_flip.prc')
assert core.DoctorScene(bpy.context, ('ANIM',)).armature == obj
assert not core.run_checks(bpy.context, ('ANIM',), {'export_paths'})
model_results = core.run_checks(bpy.context, ('MODEL',), {'export_paths'})
assert {r.payload['property'] for r in model_results if r.blocking} >= {'vanilla_update_prc','vanilla_nusktb'}, model_results
bpy.data.objects.remove(model)
reports = []
bpy.context.scene.sub_doctor.run_before_export = True
bpy.context.scene.sub_doctor.block_on_errors = True
assert ui.preflight(bpy.context, SimpleNamespace(report=lambda level,msg: reports.append(msg)), 'ANIM'), reports

for frame in (1,5,9):
    bpy.context.scene.frame_set(frame)
    for i,name in enumerate(('Trans','Accessory.L','Accessory.R','Ribbon','Only.Left')):
        bone = obj.pose.bones[name]
        bone.rotation_mode = 'QUATERNION'
        bone.location = (i*.1, frame*.13*(i+1), i*.04)
        bone.rotation_quaternion = (1,.03*frame,.02*i,0)
        bone.scale = (1,1,1)
        flip.keyframe_pose_bones([bone],frame)
action = obj.animation_data.action
# Standard imported tracks are cached, newly created custom bones are absent.
flip.store_smash_pose_cache(action, {'1': {'Trans': {'translation':[0,0,0], 'rotation':[0,0,0,1], 'scale':[1,1,1]}}})
# Interleaved one-sided keys exercise snapshotting before destination writes.
obj.pose.bones['Accessory.L'].location.y = 2.1
obj.pose.bones['Accessory.L'].keyframe_insert('location',frame=3)
frames = mirror._frames_for_action(action,False,bpy.context.scene)
source = {}
for frame in frames:
    bpy.context.scene.frame_set(frame)
    source[frame] = {p.name:p.matrix_basis.copy() for p in obj.pose.bones}
# Axis-angle is also keyed correctly.
obj.pose.bones['Ribbon'].rotation_mode = 'AXIS_ANGLE'
bpy.context.scene.frame_set(5)
mirror.mirror_action_smash_y(action, context=bpy.context, include_fingers=True)
assert bpy.context.scene.frame_current == 5
H = Matrix.Diagonal((1,-1,1,1))
def error(a,b):
    return max(abs(a[r][c]-b[r][c]) for r in range(4) for c in range(4))
for frame in frames:
    bpy.context.scene.frame_set(frame)
    for src,dst in [('Accessory.L','Accessory.R'),('Accessory.R','Accessory.L'),('Only.Left','Only.Right')]:
        a=obj.data.bones[src].matrix_local.to_3x3().normalized().to_4x4()
        b=obj.data.bones[dst].matrix_local.to_3x3().normalized().to_4x4()
        change=b.inverted()@H@a
        expected=change@source[frame][src]@change.inverted()
        assert error(obj.pose.bones[dst].matrix_basis, expected)<1e-5, (frame,src,dst,error(obj.pose.bones[dst].matrix_basis, expected))
# Broader naming works in the shared Smash path even when only one side animated.
assert flip.create_mirror_map(obj.pose.bones.keys())['Only.Left']=='Only.Right'
data={'Only.Left':{'translation':[1,2,3],'rotation':[0,0,0,1]}}
assert 'Only.Right' in flip.mirror_smash_pose_data(data,mirror_map=flip.create_mirror_map(obj.pose.bones.keys()))
# A list scanned before new components were created must not exclude those bones.
items=[SimpleNamespace(name='Accessory.L',include=False)]
assert flip.collect_unchecked_custom_mirror_bones(obj,items)=={'Accessory.L'}
# Build actual hashed-name components and verify semantic controller pairing.
cc = importlib.import_module(MODULE + '.source.extras.custom_components')
custom = importlib.import_module(MODULE + '.source.extras.mirror_custom_bones')
editor = bpy.context.scene.sub_component_editor
editor.armature = obj
editor.save_on_build = False
for name, kind, bones in [('Floating Feet','ISOLATED',['Accessory.L','Accessory.R']), ('Eye motion','EYES',['Ribbon'])]:
    c = editor.components.add()
    c.name, c.kind = name, kind
    for n in bones:
        c.bones.add().bone = n
assert bpy.ops.sub.component_build() == {'FINISHED'}
controls = custom.control_mirror_map(obj)
isolated = {}
for n in ('Accessory.L','Accessory.R'):
    con = next(c for c in obj.pose.bones[n].constraints if c.type == 'COPY_TRANSFORMS')
    isolated[n] = obj.pose.bones[con.subtarget].parent.name
assert controls[isolated['Accessory.L']] == isolated['Accessory.R']
assert controls[isolated['Accessory.R']] == isolated['Accessory.L']
pad = next(p for p in obj.pose.bones if p.name.endswith('_Look'))
assert not flip.should_exclude_bone_from_mirroring(pad.name,obj)
pad.location = (.3,.7,0)
snapshot = custom.snapshot_custom_pose(obj,{pad.name},controls)
assert abs(snapshot[pad.name].translation.x+.3)<1e-6
assert abs(snapshot[pad.name].translation.y-.7)<1e-6
# Rest poses remain neutral even for repositioned and rolled controls.
for name in isolated.values():
    obj.pose.bones[name].matrix_basis = Matrix.Identity(4)
snapshot = custom.snapshot_custom_pose(obj,set(isolated.values()),controls)
assert all(error(m,Matrix.Identity(4))<1e-5 for m in snapshot.values())
assert 'ArmR' in flip.mirror_smash_pose_data({'ArmL':{'translation':[1,2,3],'rotation':[0,0,0,1]}})
print('EXPORT SCOPE AND CUSTOM MIRROR TEST PASSED')
