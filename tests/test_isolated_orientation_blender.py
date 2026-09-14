from pathlib import Path
fixture=Path(__file__).with_name('test_components_lifecycle_blender.py')
exec(compile(fixture.read_text(encoding='utf-8').split("editor.save_on_build = False")[0],str(fixture),'exec'))
from mathutils import Matrix, Euler
editor.save_on_build=False
for pb in obj.pose.bones:
    pb.rotation_mode='XYZ'
obj.pose.bones['Trans'].rotation_euler=(0,0,3.14159265)
obj.pose.bones['Head'].rotation_euler=(.3,-.6,.8)
obj.pose.bones['LidUpper'].rotation_euler=(1.2,.4,-.9)
obj.pose.bones['LidLower'].rotation_euler=(-.7,.8,.2)
bpy.context.view_layer.update()
def matrices():
    ev=obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
    return {n:ev.pose.bones[n].matrix.copy() for n in ('LidUpper','LidLower')}
before=matrices()
c=component('ISOLATED','Floating Feet',['LidUpper','LidLower'])
c=editor.components[-1]
c.control_rotation=(.2,.5,-.3)
c.control_offset=(.4,-.2,.1)
assert bpy.ops.sub.component_build()=={'FINISHED'}
after=matrices()
for n in before:
    err=max(abs(before[n][r][k]-after[n][r][k]) for r in range(4) for k in range(4))
    print(n,err,flush=True)
    assert err<2e-5,(n,err)
# Simulate an older component with an inverted output helper and repair it.
helpers=[p.name for p in obj.pose.bones if p.bone.get('sub_face_helper')]
for p in obj.pose.bones:
    if p.bone.get('sub_isolated_version'):
        del p.bone['sub_isolated_version']
bpy.ops.object.mode_set(mode='EDIT')
for n in helpers:
    b=obj.data.edit_bones[n]
    b.matrix=b.matrix @ Matrix.Rotation(3.14159265,4,'Y')
bpy.ops.object.mode_set(mode='POSE')
assert bpy.ops.sub.component_build()=={'FINISHED'}
for n,mat in matrices().items():
    err=max(abs(before[n][r][k]-mat[r][k]) for r in range(4) for k in range(4))
    assert err<2e-5,(n,err)
# Rotation-controller visibility changes immediately, without rebuilding.
c=component('EYES','Eye toggle',['EyeL'])
assert bpy.ops.sub.component_build()=={'FINISHED'}
c=editor.components[-1]
pivot=obj.pose.bones[cc.control_name(obj,c)]
c.show_orbit=True
assert not pivot.bone.hide and not pivot.bone.hide_select
assert any(col.is_visible for col in pivot.bone.collections)
c.show_orbit=False
assert pivot.bone.hide and pivot.bone.hide_select
assert all(not col.is_visible for col in pivot.bone.collections)
if hasattr(pivot,'hide'):
    assert pivot.hide
face.set_orbit_visibility(obj,c,force_show=True)
assert not pivot.bone.hide and any(col.is_visible for col in pivot.bone.collections)
face.set_orbit_visibility(obj,c)
assert pivot.bone.hide
print('ISOLATED ORIENTATION, LEGACY REPAIR AND EYE VISIBILITY PASSED')
