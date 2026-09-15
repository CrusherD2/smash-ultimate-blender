from pathlib import Path
fixture = Path(__file__).with_name('test_custom_components_blender.py')
exec(compile(fixture.read_text(encoding='utf-8').split('components = [')[0],str(fixture),'exec'))
rig = importlib.import_module(MODULE + '.source.extras.create_animation_rig')
appearance = importlib.import_module(MODULE + '.source.extras.control_appearance')
bpy.ops.object.mode_set(mode='EDIT')
for name in ('FootL','FootR','FootL.001','FootR2'):
    bone(name,(0,0,0),'Trans')
bpy.ops.object.mode_set(mode='POSE')
rig._apply_shapes(bpy.context,obj)
obj.data[rig.ARMATURE_FLAG]=True
feet = [obj.pose.bones[n] for n in ('FootL','FootR','FootL.001','FootR2')]
for pb in feet:
    assert pb.custom_shape is not None
    assert len(pb.custom_shape.data.vertices) >= 8
    assert len({round(v.co.z,4) for v in pb.custom_shape.data.vertices}) > 1
# Reopening repairs missing standard shapes, without changing animation or visibility.
feet[0].custom_shape=None
feet[0].bone.hide=True
feet[0].location=(.2,.3,.4)
feet[0].keyframe_insert('location',frame=1)
# Explicitly removed and individually customized shapes remain intentional.
feet[1].custom_shape=None
appearance.remember(feet[1])
feet[2].custom_shape=rig._widget_object(bpy.context,'circle')
custom=feet[2].custom_shape
assert rig.repair_foot_control_shapes(bpy.context,obj)==1
assert feet[0].custom_shape and feet[0].bone.hide
assert abs(feet[0].location.x-.2)<1e-6
assert feet[1].custom_shape is None and feet[2].custom_shape == custom
assert rig.repair_foot_control_shapes(bpy.context,obj)==0
feet[0].custom_shape=None
obj.data[rig.ARMATURE_FLAG]=False
assert rig.repair_foot_control_shapes(bpy.context,obj)==0
assert feet[0].custom_shape is None
obj.data[rig.ARMATURE_FLAG]=True
rig._ensure_ik_drivers_on_loaded_rigs()
assert feet[0].custom_shape
print('REGULAR FOOT BOX CREATION AND RELOAD REPAIR PASSED')
