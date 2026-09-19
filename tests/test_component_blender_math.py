"""Compare detached constraint output to Blender, before residual correction."""
from pathlib import Path
fixture=Path(__file__).with_name('test_addon_registration_blender.py')
exec(compile(fixture.read_text(encoding='utf-8-sig').split('addon_utils.disable(MODULE')[0],str(fixture),'exec'))
import random
from mathutils import Matrix, Vector
graph_module=importlib.import_module(MODULE+'.source.extras.component_graph')
data=bpy.data.armatures.new('Component constraint parity')
obj=bpy.data.objects.new('Component constraint parity',data)
bpy.context.scene.collection.objects.link(obj)
bpy.context.view_layer.objects.active=obj
obj.select_set(True)
bpy.ops.object.mode_set(mode='EDIT')
for name in ('Root','Owner','Target'):
    bone=data.edit_bones.new(name)
    bone.head=(0,0,0);bone.tail=(0,1,0)
data.edit_bones['Owner'].parent=data.edit_bones['Root']
bpy.ops.object.mode_set(mode='POSE')
owner=obj.pose.bones['Owner'];target=obj.pose.bones['Target'];root=obj.pose.bones['Root']
owner.rotation_mode='XYZ'
con=owner.constraints.new('TRANSFORM')
con.target=obj;con.subtarget='Target';con.owner_space=con.target_space='LOCAL'
con.map_from='LOCATION';con.map_to='ROTATION';con.mix_mode_rot='AFTER'
for axis in 'xyz':
    setattr(con,'from_min_'+axis,-1);setattr(con,'from_max_'+axis,1)
    setattr(con,'to_min_'+axis+'_rot',-.7);setattr(con,'to_max_'+axis+'_rot',1.1)
    setattr(con,'map_to_'+axis+'_from',axis.upper())
rng=random.Random(151)
worst=0.0;count=0
def check(graph,tolerance=2e-5):
    global worst,count
    obj.update_tag();bpy.context.view_layer.update()
    graph.samples={'Root':root.matrix.copy()}
    native=graph.evaluate().pose.bones['Owner'].matrix
    expected=owner.matrix
    error=max(abs(native[r][c]-expected[r][c]) for r in range(4) for c in range(4))
    worst=max(worst,error);count+=1
    assert error<tolerance,(count,error,native,expected)
for order in ('XYZ','XZY','YXZ','YZX','ZXY','ZYX'):
    con.to_euler_order=order
    graph=graph_module.capture(obj,{'Owner'},{'Target'},{'Root','Owner'})
    assert graph,graph_module.LAST_DIAGNOSTICS
    try:
        for i in range(12):
            owner.location=[rng.uniform(-1,1) for _ in range(3)]
            owner.rotation_euler=[rng.uniform(-2,2) for _ in range(3)]
            owner.scale=[rng.uniform(.2,2)*( -1 if i%3==0 and j==0 else 1) for j in range(3)]
            target.location=[rng.uniform(-2,2) for _ in range(3)]
            root.rotation_mode='XYZ';root.rotation_euler=(.2,.1,-.3)
            check(graph)
    finally:
        graph.close()
owner.constraints.remove(con)
con=owner.constraints.new('DAMPED_TRACK')
con.target=obj;con.subtarget='Target'
root.matrix_basis=Matrix.Identity(4);owner.matrix_basis=Matrix.Identity(4)
for axis in ('X','Y','Z','NEGATIVE_X','NEGATIVE_Y','NEGATIVE_Z'):
    # RNA spells the negative track directions TRACK_NEGATIVE_X, etc.
    con.track_axis='TRACK_'+axis
    graph=graph_module.capture(obj,{'Owner'},{'Target'},{'Root','Owner'})
    assert graph,graph_module.LAST_DIAGNOSTICS
    try:
        direction=Vector((0,0,0));direction['XYZ'.index(axis[-1])]=-1 if axis.startswith('NEGATIVE') else 1
        for factor in (0,1,-1):
            for epsilon in (0,1e-7,1e-3):
                target.location=direction*factor+Vector((epsilon,epsilon,epsilon))
                check(graph)
    finally:
        graph.close()
con.influence=.5
for scale in ((1,1,1),(2,.7,1.3),(-1,2,.8)):
    obj.rotation_euler=(.3,-.2,.7);obj.scale=scale;obj.location=(4,2,-1)
    bpy.context.view_layer.update()
    graph=graph_module.capture(obj,{'Owner'},{'Target'},{'Root','Owner'})
    assert graph,graph_module.LAST_DIAGNOSTICS
    try:
        for i in range(12):
            owner.rotation_euler=[rng.uniform(-2,2) for _ in range(3)]
            target.location=[rng.uniform(-2,2) for _ in range(3)]
            check(graph)
    finally:
        graph.close()
# Animated influence must refresh the captured settings, including zero.
for frame,value in ((1,0),(2,.3),(3,1)):
    con.influence=value;con.keyframe_insert('influence',frame=frame)
bpy.context.scene.frame_set(1)
graph=graph_module.capture(obj,{'Owner'},{'Target'},{'Root','Owner'})
assert graph,graph_module.LAST_DIAGNOSTICS
try:
    for frame in (1,2,3,1):
        bpy.context.scene.frame_set(frame)
        check(graph)
finally:
    graph.close()
obj.animation_data_clear()
owner.constraints.remove(con)
for connected in (False,True):
    bpy.ops.object.mode_set(mode='EDIT')
    edit=data.edit_bones['Owner']
    edit.head=(0,1,0);edit.tail=(.2,2,.1)
    edit.use_connect=connected
    bpy.ops.object.mode_set(mode='POSE')
    owner=obj.pose.bones['Owner'];root=obj.pose.bones['Root'];target=obj.pose.bones['Target']
    con=owner.constraints.new('COPY_TRANSFORMS')
    con.target=obj;con.subtarget='Target';con.owner_space='POSE';con.target_space='LOCAL';con.mix_mode='AFTER_FULL';con.influence=.4
    for mode in ('FULL','FIX_SHEAR','ALIGNED','AVERAGE','NONE','NONE_LEGACY'):
        owner.bone.inherit_scale=mode
        for rotate,local_location in ((True,True),(False,True),(True,False),(False,False)):
            owner.bone.use_inherit_rotation=rotate;owner.bone.use_local_location=local_location
            root.scale=(2,.7,-1.3);root.rotation_euler=(.2,.7,-.4)
            owner.location=(.2,-.3,.4);owner.rotation_euler=(.3,-.7,.2);owner.scale=(1.1,.8,1.4)
            target.location=(.3,-.1,.2);target.rotation_mode='XYZ';target.rotation_euler=(.4,.1,-.2)
            graph=graph_module.capture(obj,{'Owner'},{'Target'},{'Root','Owner'})
            assert graph,graph_module.LAST_DIAGNOSTICS
            try:
                check(graph)
            finally:
                graph.close()
    owner.constraints.remove(con)
# All supported full-matrix Copy Transforms orders/spaces, at partial influence.
con=owner.constraints.new('COPY_TRANSFORMS');con.target=obj;con.subtarget='Target';con.owner_space='POSE'
for mode in ('REPLACE','AFTER_FULL','BEFORE_FULL'):
    con.mix_mode=mode
    for space in ('LOCAL','POSE'):
        con.target_space=space
        for influence in (.25,1):
            con.influence=influence
            graph=graph_module.capture(obj,{'Owner'},{'Target'},{'Root','Owner'})
            assert graph,graph_module.LAST_DIAGNOSTICS
            try:
                check(graph)
            finally:
                graph.close()
print('BLENDER CONSTRAINT MATH PARITY PASSED',count,'cases; worst error',worst)
