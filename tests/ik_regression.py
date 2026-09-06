"""Blender --background --factory-startup --python-exit-code 1 --python tests/ik_regression.py"""
from pathlib import Path
import importlib
import sys
import types
import math
import bpy
from mathutils import Matrix, Euler

ROOT = Path(__file__).resolve().parents[1]
for name, path in [('sut', ROOT), ('sut.source', ROOT/'source'), ('sut.source.extras', ROOT/'source/extras'), ('sut.source.anim', ROOT/'source/anim')]:
    mod = types.ModuleType(name)
    mod.__path__ = [str(path)]
    sys.modules[name] = mod
rig = importlib.import_module('sut.source.extras.create_animation_rig')
ik = importlib.import_module('sut.source.extras.ik_channels')
fk = importlib.import_module('sut.source.extras.fk_to_ik')
compat = importlib.import_module('sut.source.anim.fcurve_compat')
extras = importlib.import_module('sut.source.extras.anim_rig_extras')
apply = importlib.import_module('sut.source.extras.apply_ik_animation')
for prop, update in [('sub_use_ik',rig._update_use_ik), ('sub_use_ik_arms',rig._update_use_ik_arms), ('sub_use_ik_legs',rig._update_use_ik_legs)]:
    setattr(bpy.types.Armature, prop, bpy.props.FloatProperty(default=0, min=0, max=1, update=update))
bpy.app.handlers.frame_change_post.append(rig._sync_ik_fk_visibility)
bpy.utils.register_class(fk.SUB_OP_fk_to_ik_transfer)
bpy.utils.register_class(rig.SUB_OP_anim_rig_toggle_ik_fk)
bpy.utils.register_class(rig.SUB_OP_create_animation_rig)
for file, cls in [('create_ik_legs','SUB_OP_create_foot_ik_operator'), ('create_ik_arms','SUB_OP_create_arm_ik_operator'), ('create_ik_armsandlegs','SUB_OP_create_ik_bones_operator')]:
    bpy.utils.register_class(getattr(importlib.import_module('sut.source.extras.'+file),cls))


def build():
    bpy.ops.object.mode_set(mode='OBJECT') if bpy.context.object and bpy.context.object.mode != 'OBJECT' else None
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)
    data = bpy.data.armatures.new('Regression')
    obj = bpy.data.objects.new('Regression', data)
    bpy.context.collection.objects.link(obj)
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    bpy.ops.object.mode_set(mode='EDIT')
    def bone(name, head, tail, parent=None):
        b = data.edit_bones.new(name)
        b.head, b.tail = head, tail
        if parent:
            b.parent = data.edit_bones[parent]
        return b
    bone('Trans', (0,0,0), (0,1,0))
    bone('Hip', (0,0,0), (0,1,0), 'Trans')
    for side, sign in [('L',1), ('R',-1)]:
        x=sign
        bone('Leg'+side,(x,0,0),(x,.2,-2),'Hip')
        bone('Knee'+side,(x,.2,-2),(x,0,-4),'Leg'+side)
        bone('Foot'+side,(x,0,-4),(x,-1,-4),'Knee'+side)
        bone('Shoulder'+side,(x,0,2),(x*3,.2,2),'Hip')
        bone('Arm'+side,(x*3,.2,2),(x*5,0,2),'Shoulder'+side)
        bone('Hand'+side,(x*5,0,2),(x*6,0,2),'Arm'+side)
    bpy.ops.object.mode_set(mode='POSE')
    bpy.context.scene.frame_start=1
    bpy.context.scene.frame_end=12
    for frame in range(1,13):
        bpy.context.scene.frame_set(frame)
        for pb in obj.pose.bones:
            pb.rotation_mode='QUATERNION'
            if pb.name.startswith(('Leg','Knee','Arm','Shoulder')):
                angle=0.35*math.sin(frame*.3)
                pb.rotation_quaternion=Matrix.Rotation(angle,4,'X' if pb.name.startswith(('Leg','Knee')) else 'Z').to_quaternion()
            if pb.name=='Hip':
                pb.location.x=.1*frame
            pb.keyframe_insert('rotation_quaternion',frame=frame)
            pb.keyframe_insert('location',frame=frame)
    bpy.context.scene.frame_set(1)
    return obj


def snapshot(obj, names):
    out={}
    for f in range(1,13):
        bpy.context.scene.frame_set(f)
        bpy.context.view_layer.update()
        out[f]={n:obj.pose.bones[n].matrix.copy() for n in names}
    return out


def error(actual, reference):
    return max((max(abs(actual[f][n][i][j]-reference[f][n][i][j]) for i in range(4) for j in range(4)),f,n) for f in reference for n in reference[f])


def curves(obj, names):
    paths=tuple(obj.pose.bones[n].path_from_id()+'.' for n in names)
    return {(fc.data_path,fc.array_index): (fc.mute, tuple((tuple(k.co),k.interpolation) for k in fc.keyframe_points)) for fc in compat.get_all_action_fcurves(obj.animation_data.action, id_type='OBJECT') if fc.data_path.startswith(paths)}


for kind in ('LEGS','ARMS','BOTH'):
    obj=build()
    names=[pb.name for pb in obj.pose.bones]
    reference=snapshot(obj,names)
    original_curves=curves(obj,names)
    create={'LEGS':bpy.ops.sub.create_foot_ik,'ARMS':bpy.ops.sub.create_arm_ik,'BOTH':bpy.ops.sub.create_ik_bones}[kind]
    assert create(match_position=False)=={'FINISHED'}
    assert extras.animation_needs_ik_match(obj)
    assert not obj.data.animation_data, 'Creation added switch keys'
    assert bpy.ops.sub.fk_to_ik_transfer(cleanup_mode=kind,entire_animation=True,show_progress=False)=={'FINISHED'}
    assert not extras.animation_needs_ik_match(obj)
    assert not obj.data.animation_data, 'Matching added switch keys'
    assert curves(obj,names)==original_curves, 'Matching changed FK keys'
    obj.data.sub_use_ik_arms=1
    obj.data.sub_use_ik_legs=1
    obj.update_tag()
    actual=snapshot(obj,names)
    worst=error(actual,reference)
    print(kind,'MAX MATRIX ERROR',worst)
    assert worst[0]<.002, worst
    # FK edits cannot affect the full IK result.
    chain_names=apply.collect_fk_bone_names(obj,limbs=kind)
    pb=obj.pose.bones[chain_names[0]]
    fc=compat.find_fcurve(obj.animation_data.action,pb.path_from_id()+'.rotation_quaternion',index=1,id_type='OBJECT')
    old=fc.keyframe_points[5].co.y
    fc.keyframe_points[5].co.y+=.6
    fc.update()
    assert error(snapshot(obj,names),actual)[0]<.002, 'FK leaked into IK'
    fc.keyframe_points[5].co.y=old
    fc.update()
    # IK control edits must also be invisible in full FK mode.
    obj.data.sub_use_ik_arms=0
    obj.data.sub_use_ik_legs=0
    fk_reference=snapshot(obj,names)
    target=next(ik.chains(obj,kind))[2]
    target_pb=obj.pose.bones[target]
    target_fc=compat.find_fcurve(obj.animation_data.action,target_pb.path_from_id()+'.location',index=0,id_type='OBJECT')
    target_old=target_fc.keyframe_points[5].co.y
    target_fc.keyframe_points[5].co.y+=5
    target_fc.update()
    assert error(snapshot(obj,names),fk_reference)[0]<.002, 'IK leaked into FK'
    target_fc.keyframe_points[5].co.y=target_old
    target_fc.update()
    # One destination key per press, with no pose keys authored by switching.
    bpy.context.scene.frame_set(1)
    saved=curves(obj,list(obj.pose.bones.keys()))
    assert bpy.ops.sub.anim_rig_toggle_ik_fk(limbs=kind,set_enabled=True,enable_ik=False)=={'FINISHED'}
    switch=compat.get_all_action_fcurves(obj.data.animation_data.action,id_type='ARMATURE')
    switch=[c for c in switch if c.data_path.startswith('sub_use_ik')]
    assert all(len(c.keyframe_points)==1 and c.keyframe_points[0].co.y==0 for c in switch)
    bpy.context.scene.frame_set(12)
    assert bpy.ops.sub.anim_rig_toggle_ik_fk(limbs=kind,set_enabled=True,enable_ik=True)=={'FINISHED'}
    assert all(len(c.keyframe_points)==2 for c in switch)
    assert curves(obj,list(obj.pose.bones.keys()))==saved, 'Switch rewrote animation'
    assert all(0.1<c.evaluate(6.5)<.9 for c in switch), 'No smooth blend'
    mixed=snapshot(obj,names)
    # Bake only the owned chains and leave all unrelated channels intact.
    unrelated=[n for n in names if n not in chain_names]
    keep=curves(obj,unrelated)
    apply.bake_and_clean_current_action(bpy.context,obj,limbs=kind)
    assert not rig.armature_has_ik(obj)
    assert not any(n.startswith(ik.PREFIX) for n in obj.pose.bones.keys())
    assert curves(obj,unrelated)==keep, 'Bake changed unrelated bones'
    baked=snapshot(obj,names)
    assert error(baked,mixed)[0]<.002, error(baked,mixed)
    print('PASS',kind,'match, independence, switch keys, blend, scoped bake/removal')

# Partial matching/removal with both limb types already present.
obj=build()
ik.create_controls(bpy.context,obj,'BOTH')
ik.match(bpy.context,obj,'LEGS')
assert ik.unmatched(obj,obj.animation_data.action)=={'ARMS'}
ik.match(bpy.context,obj,'ARMS',entire=False)
assert extras.animation_needs_ik_match(obj), 'A single-frame match marked the whole animation'
ik.match(bpy.context,obj,'ARMS')
assert not extras.animation_needs_ik_match(obj)
arm_names=[n for _, group, target, pole in ik.chains(obj,'ARMS') for n in (*group,*(ik.PREFIX+x for x in group),target,pole)]
arm_curves=curves(obj,arm_names)
apply.bake_and_clean_current_action(bpy.context,obj,limbs='LEGS')
assert rig.armature_has_ik(obj,'ARMS') and not rig.armature_has_ik(obj,'LEGS')
assert curves(obj,arm_names)==arm_curves
ik.create_controls(bpy.context,obj,'LEGS')
assert ik.unmatched(obj,obj.animation_data.action)=={'LEGS'}, 'Recreated controls retained stale match flag'
original=obj.animation_data.action
new=bpy.data.actions.new('Unmatched new animation')
assign=importlib.import_module('sut.source.blender_compat').assign_action
assign(obj.animation_data,new)
assert extras.animation_needs_ik_match(obj)
assign(obj.animation_data,original)
ik.match(bpy.context,obj,'LEGS')
assert not extras.animation_needs_ik_match(obj)
print('PASS action changes, single-frame/partial matching, partial removal/recreation')

for kind in ('ARMS','LEGS','BOTH'):
    obj=build()
    assert bpy.ops.sub.create_animation_rig(stage='IK',ik_limbs=kind,setup_eye_look=False,setup_finger_sliders=False,hide_helpers=False,match_position=True)=={'FINISHED'}
    assert not obj.data.animation_data, 'Animation Rig creation keyed switches'
    assert not extras.animation_needs_ik_match(obj)
    assert rig.armature_has_ik(obj,'ARMS')==(kind in ('ARMS','BOTH'))
    assert rig.armature_has_ik(obj,'LEGS')==(kind in ('LEGS','BOTH'))
    print('PASS Animation Rig creation',kind)


def stress(obj):
    names=[n for n in obj.pose.bones.keys() if n.startswith(('Shoulder','Arm','Hand','Leg','Knee','Foot')) and not 'IK' in n]
    obj.animation_data_clear()
    obj.data.animation_data_clear()
    obj.data.sub_use_ik_arms=0
    obj.data.sub_use_ik_legs=0
    for f in range(1,13):
        bpy.context.scene.frame_set(f)
        for n in names:
            pb=obj.pose.bones[n]
            pb.rotation_mode='QUATERNION'
            pb.rotation_quaternion=Euler((.25*math.sin(f), .7*f, .15*math.cos(f)), 'XYZ').to_quaternion()
            if f in (4,5,6):
                pb.rotation_quaternion=(1,0,0,0)
            pb.keyframe_insert('rotation_quaternion',frame=f)
    ref=snapshot(obj,names)
    ik.create_controls(bpy.context,obj,'BOTH')
    ik.match(bpy.context,obj,'BOTH')
    obj.data.sub_use_ik_arms=1
    obj.data.sub_use_ik_legs=1
    actual=snapshot(obj,names)
    worst=error(actual,ref)
    print('STRESS',obj.name,'MAX MATRIX ERROR',worst)
    assert worst[0]<.005,worst


stress(build())
if '--' in sys.argv:
    filename=sys.argv[sys.argv.index('--')+1]
    with bpy.data.libraries.load(filename,link=False) as (src,dst):
        dst.armatures=[n for n in src.armatures if n.startswith('smush_blender_import')][:1]
    assert dst.armatures, 'No Smash armature in fixture file'
    bpy.ops.object.mode_set(mode='OBJECT')
    obj=bpy.data.objects.new('Character geometry regression',dst.armatures[0])
    bpy.context.collection.objects.link(obj)
    bpy.context.view_layer.objects.active=obj
    obj.select_set(True)
    bpy.ops.object.mode_set(mode='POSE')
    # Use only rest data from the file; never change or save the original file.
    stress(obj)

# Button destinations follow the evaluated rig after switching and scrubbing.
obj=build()
ik.create_controls(bpy.context,obj,'BOTH')
ik.match(bpy.context,obj,'BOTH')
class LayoutCapture:
    def __init__(self): self.buttons=[]
    def row(self, **kwargs): return self
    def label(self, **kwargs): pass
    def operator(self, identifier, **kwargs):
        op=types.SimpleNamespace(identifier=identifier, **kwargs)
        self.buttons.append(op)
        return op
for frame, enabled in ((1,False),(12,True),(1,False),(12,True)):
    bpy.context.scene.frame_set(frame)
    bpy.ops.sub.anim_rig_toggle_ik_fk(limbs='BOTH',set_enabled=True,enable_ik=enabled)
    bpy.context.view_layer.update()
    layout=LayoutCapture()
    extras._draw_ik_fk_switch_rows(layout,obj)
    assert len(layout.buttons)==3
    assert all(b.enable_ik != enabled for b in layout.buttons), (frame,enabled,layout.buttons)
    assert all(b.text==('Switch to FK' if enabled else 'Switch to IK') for b in layout.buttons)
for frame, enabled in ((1,False),(12,True)):
    bpy.context.scene.frame_set(frame)
    bpy.context.view_layer.update()
    layout=LayoutCapture()
    extras._draw_ik_fk_switch_rows(layout,obj)
    assert all(b.enable_ik != enabled for b in layout.buttons), 'Stale button after scrub'
print('PASS evaluated switch button destinations')

# Cleaning reduces both streams and leaves other limbs and switch curves untouched.
arm_names=[n for _,group,target,pole in ik.chains(obj,'ARMS') for n in (*group,*(ik.PREFIX+x for x in group),target,pole)]
arm_curves=curves(obj,arm_names)
switch_curves=[(fc.data_path,[(tuple(k.co),k.interpolation) for k in fc.keyframe_points])
               for fc in compat.get_all_action_fcurves(obj.data.animation_data.action,id_type='ARMATURE')]
leg_names=[n for _,group,target,pole in ik.chains(obj,'LEGS') for n in (*group,*(ik.PREFIX+x for x in group),target,pole)]
leg_paths=tuple(obj.pose.bones[n].path_from_id()+'.' for n in leg_names)
curves_before={ (fc.data_path,fc.array_index): [fc.evaluate(1+i*.25) for i in range(45)]
               for fc in compat.get_all_action_fcurves(obj.animation_data.action,id_type='OBJECT') if fc.data_path.startswith(leg_paths)}
counts_before={n:sum(len(fc.keyframe_points) for fc in compat.get_all_action_fcurves(obj.animation_data.action,id_type='OBJECT') if fc.data_path.startswith(obj.pose.bones[n].path_from_id()+'.')) for n in leg_names}
removed=ik.clean_animation(obj,'LEGS')
assert removed>0
assert curves(obj,arm_names)==arm_curves
for fc in compat.get_all_action_fcurves(obj.animation_data.action,id_type='OBJECT'):
    key=(fc.data_path,fc.array_index)
    if key in curves_before:
        assert max(abs(fc.evaluate(1+i*.25)-v) for i,v in enumerate(curves_before[key]))<=1.01e-4
counts_after={n:sum(len(fc.keyframe_points) for fc in compat.get_all_action_fcurves(obj.animation_data.action,id_type='OBJECT') if fc.data_path.startswith(obj.pose.bones[n].path_from_id()+'.')) for n in leg_names}
assert any(counts_after[n]<counts_before[n] for n in leg_names if not 'IK' in n), 'FK was not reduced'
assert any(counts_after[n]<counts_before[n] for n in leg_names if 'IK' in n), 'IK was not reduced'
assert switch_curves==[(fc.data_path,[(tuple(k.co),k.interpolation) for k in fc.keyframe_points]) for fc in compat.get_all_action_fcurves(obj.data.animation_data.action,id_type='ARMATURE')]
assert bpy.ops.sub.fk_to_ik_transfer(cleanup_mode='LEGS',entire_animation=True,clean_animation=True,show_progress=False)=={'FINISHED'}
print('PASS clean animation: FK and IK reduction, quarter-frame tolerance, limb scope, switch preservation;',removed,'keys removed')
