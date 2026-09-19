"""Direct native/Blender parity for custom driver math and added constraints."""
from pathlib import Path
fixture=Path(__file__).with_name('test_addon_registration_blender.py')
exec(compile(fixture.read_text(encoding='utf-8-sig').split('addon_utils.disable(MODULE')[0],str(fixture),'exec'))
import random
from mathutils import Matrix
graph_module=importlib.import_module(MODULE+'.source.extras.component_graph')
data=bpy.data.armatures.new('Driver constraint parity')
obj=bpy.data.objects.new('Driver constraint parity',data)
bpy.context.scene.collection.objects.link(obj)
bpy.context.view_layer.objects.active=obj;obj.select_set(True)
bpy.ops.object.mode_set(mode='EDIT')
for name in ('Root','Owner','Target','Control'):
    bone=data.edit_bones.new(name);bone.head=(.2,1,0) if name=='Owner' else (0,0,0);bone.tail=bone.head+__import__('mathutils').Vector((.1,1,.2))
data.edit_bones['Owner'].parent=data.edit_bones['Root']
data.edit_bones['Target'].parent=data.edit_bones['Root']
bpy.ops.object.mode_set(mode='POSE')
owner=obj.pose.bones['Owner'];target=obj.pose.bones['Target'];root=obj.pose.bones['Root'];control=obj.pose.bones['Control']
for pb in obj.pose.bones: pb.rotation_mode='XYZ'
obj.rotation_euler=(.2,.3,-.4);obj.scale=(1.2,.8,1.4);obj.location=(2,1,-3)
rng=random.Random(983);count=0;worst=0
def update():
    obj.update_tag();bpy.context.view_layer.update()
def capture():
    update()
    result=graph_module.capture(obj,{'Owner'},{'Control','Target'},{'Owner','Root'})
    assert result,(graph_module.LAST_DIAGNOSTICS,[(fc.extrapolation,[(tuple(p.co),p.interpolation,tuple(p.handle_left),tuple(p.handle_right)) for p in fc.keyframe_points]) for fc in obj.animation_data.drivers] if obj.animation_data else [])
    return result
def check(graph,label):
    global count,worst
    update();graph.samples={'Root':root.matrix.copy()}
    actual=graph.evaluate().pose.bones['Owner'].matrix;expected=owner.matrix.copy()
    error=max(abs(a-b) for ra,rb in zip(actual,expected) for a,b in zip(ra,rb))
    worst=max(worst,error);count+=1
    assert error<4e-5,(label,error,actual,expected)
def random_pose(i):
    for pb in (owner,target,root):
        pb.location=[rng.uniform(-.5,.5) for _ in range(3)]
        pb.rotation_euler=[rng.uniform(-3.2,3.2) for _ in range(3)]
        pb.scale=[rng.uniform(.5,1.7)*(-1 if i%3==0 and j==0 else 1) for j in range(3)]

for kind in ('LIMIT_ROTATION','LIMIT_SCALE','COPY_LOCATION','COPY_ROTATION','COPY_SCALE','CHILD_OF'):
    con=owner.constraints.new(kind)
    if hasattr(con,'target'): con.target=obj;con.subtarget='Target'
    for space in ('LOCAL','POSE','WORLD') if kind!='CHILD_OF' else ('WORLD',):
        con.owner_space=space
        if hasattr(con,'target'): con.target_space=space
        for variant in range(6):
            con.influence=.4 if variant%2 else 1
            if kind=='LIMIT_ROTATION':
                con.euler_order=('XYZ','XZY','YXZ','YZX','ZXY','ZYX')[variant]
                con.use_legacy_behavior=bool(variant%2)
                for c in 'xyz':
                    setattr(con,'use_limit_'+c,c!='y' or variant%2==0)
                    setattr(con,'min_'+c,-.6);setattr(con,'max_'+c,.8)
            elif kind=='LIMIT_SCALE':
                for c in 'xyz':
                    setattr(con,'use_min_'+c,True);setattr(con,'min_'+c,.8)
                    setattr(con,'use_max_'+c,True);setattr(con,'max_'+c,1.2)
            elif kind=='COPY_LOCATION':
                con.use_offset=bool(variant%2);con.invert_x=bool(variant%3);con.use_y=bool(variant%2)
            elif kind=='COPY_SCALE':
                con.use_offset=bool(variant%2);con.use_add=bool(variant%3)
                con.use_make_uniform=bool(variant//3);con.use_y=bool(variant%2);con.power=.7
            elif kind=='COPY_ROTATION':
                con.mix_mode=('REPLACE','ADD','BEFORE','AFTER','OFFSET','REPLACE')[variant]
                con.euler_order=('XYZ','XZY','YXZ','YZX','ZXY','ZYX')[variant]
                con.invert_x=bool(variant%3);con.use_y=bool(variant%2)
            else:
                con.set_inverse_pending=False
                con.inverse_matrix=Matrix.Translation((.2,-.4,.7)) @ Matrix.Rotation(.3,4,'Z')
                con.use_location_y=variant%3!=1;con.use_rotation_x=variant%3!=2;con.use_scale_z=variant%2==0
            graph=capture()
            try:
                for i in range(5):
                    random_pose(i);check(graph,(kind,space,variant,i))
            finally: graph.close()
    owner.constraints.remove(con)

# Independent external objects are sampled each evaluation; candidate-dependent
# targets must still decline. Includes changing target transforms after capture.
external=bpy.data.objects.new('Independent external control',None)
bpy.context.scene.collection.objects.link(external)
for kind in ('COPY_LOCATION','COPY_ROTATION','COPY_SCALE','DAMPED_TRACK','CHILD_OF'):
    con=owner.constraints.new(kind);con.target=external;con.target_space=con.owner_space='WORLD';con.influence=.6
    if kind=='CHILD_OF':
        con.set_inverse_pending=False;con.inverse_matrix=Matrix.Translation((.2,.5,-.1))
    graph=capture()
    try:
        for i in range(5):
            external.location=(i/3,.7,-.2);external.rotation_euler=(i/5,.3,-.4);external.scale=(.8,1.4,1.2)
            random_pose(i);check(graph,('external',kind,i))
    finally: graph.close()
    external.parent=obj
    assert graph_module.capture(obj,{'Owner'},(),{'Owner','Root'}) is None
    assert 'depends on matched armature' in graph_module.LAST_DIAGNOSTICS['declined']
    external.parent=None;owner.constraints.remove(con)

root.matrix_basis=Matrix.Identity(4);owner.matrix_basis=Matrix.Identity(4)
obj['custom_gain']=.6
fc=owner.driver_add('location',0);driver=fc.driver;driver.type='SCRIPTED'
var=driver.variables.new();var.name='x';var.type='TRANSFORMS'
var.targets[0].id=obj;var.targets[0].bone_target='Control';var.targets[0].transform_type='LOC_X';var.targets[0].transform_space='LOCAL_SPACE'
var=driver.variables.new();var.name='gain';var.type='SINGLE_PROP'
var.targets[0].id=obj;var.targets[0].data_path='["custom_gain"]'
expressions=['sin(x)*gain+cos(x)','tan(x/4)','asin(x/3)+acos(x/3)','atan(x)+atan2(x,gain)',
             'sqrt(abs(x))+exp(x/4)','log(abs(x)+1)+log10(abs(x)+1)',
             'floor(x)+ceil(x)+trunc(x)','degrees(x)/180+radians(x)',
             'pow(x,2)+x**3','x%0.3+x//0.3','min(x,gain,0.5)+max(x,-gain,0)',
             'x if -1<x<=1 else -gain','sqrt(x) if x>0 else 0',
             '(x>0 and gain) or -gain','gain*(x!=0)+gain*(x>=1)+gain*(x<0)',
             'sin(pi*x)+cos(e*x)']
for expression in expressions:
    driver.expression=expression
    graph=capture()
    try:
        for i,x in enumerate((-2.,-.2,0.,.4,1.2)):
            control.location.x=x;obj['custom_gain']=.3+i/10;check(graph,expression)
    finally: graph.close()
for kind in ('SUM','AVERAGE','MIN','MAX'):
    driver.type=kind;graph=capture()
    try:
        for x in (-1.,0.,.5):
            control.location.x=x;check(graph,kind)
    finally: graph.close()
driver.type='SCRIPTED';driver.expression='x*gain'
input_target=driver.variables[0].targets[0]
for space in ('LOCAL_SPACE','WORLD_SPACE'):
    input_target.transform_space=space
    for channel in ('LOC_X','LOC_Y','LOC_Z','ROT_X','ROT_Y','ROT_Z','SCALE_X','SCALE_Y','SCALE_Z','SCALE_AVG'):
        input_target.transform_type=channel
        for order in ('AUTO','XYZ','ZYX') if channel.startswith('ROT') else ('AUTO',):
            input_target.rotation_mode=order
            graph=capture()
            try:
                for i in range(4):
                    control.rotation_euler=[rng.uniform(-6,6) for _ in range(3)]
                    control.scale=(.7,-1.3,1.6);control.location=(.4,-.6,.8)
                    check(graph,(space,channel,order))
            finally: graph.close()
driver.expression='sin(frame/4)*gain'
graph=capture()
try:
    for frame in (1,2,6,2):
        bpy.context.scene.frame_set(frame);check(graph,'frame driver')
finally: graph.close()
# Arbitrary driver namespace code is not replaced by a guessed native function.
bpy.app.driver_namespace['user_curve']=lambda x:x*x
driver.expression='user_curve(x)'
update()
assert graph_module.capture(obj,{'Owner'},{'Control'},{'Owner','Root'}) is None
assert 'Custom driver namespace function' in graph_module.LAST_DIAGNOSTICS['declined']
del bpy.app.driver_namespace['user_curve']
driver.expression='x*gain';update()
# A driver-computed property must not be mistaken for an independent input.
prop=obj.driver_add('["custom_gain"]');prop.driver.expression='1.0'
assert graph_module.capture(obj,{'Owner'},{'Control'},{'Owner','Root'}) is None
assert 'Driver-computed custom property' in graph_module.LAST_DIAGNOSTICS['declined']
print('CUSTOM DRIVER AND CONSTRAINT MATH PARITY PASSED',count,'cases; worst error',worst)
