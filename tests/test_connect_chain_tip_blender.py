from pathlib import Path
fixture=Path(__file__).with_name('test_addon_registration_blender.py')
exec(compile(fixture.read_text(encoding='utf-8').split('addon_utils.disable(MODULE')[0],str(fixture),'exec'))
chain=importlib.import_module(MODULE+'.source.extras.bone_chain')
from mathutils import Vector
bpy.ops.object.armature_add(enter_editmode=True)
obj=bpy.context.object
bones=obj.data.edit_bones
bones.remove(bones[0])
parent=None
for name,head in [('Start',(0,0,0)),('Middle',(3,0,0)),('End',(5,1,0))]:
    b=bones.new(name)
    b.head=head
    b.tail=Vector(head)+Vector((0,0,.5))
    b.parent=parent
    parent=b
heads={b.name:b.head.copy() for b in bones}
assert chain.connect_chains_from_roots([bones['Start']])==2
assert all((b.head-heads[b.name]).length<1e-6 for b in bones)
assert (bones['End'].tail-Vector((7,2,0))).length<1e-6
assert bones['Middle'].use_connect and bones['End'].use_connect
# Repeated use keeps the same terminal position.
assert chain.connect_chains_from_roots([bones['Start']])==2
assert (bones['End'].tail-Vector((7,2,0))).length<1e-6
# An isolated selected bone has no chain and is left alone.
b=bones.new('Alone')
b.head=(9,0,0)
b.tail=(9,0,1)
assert chain.connect_chains_from_roots([b])==0
assert (b.tail-Vector((9,0,1))).length<1e-6
print('CONNECT CHAIN TERMINAL EXTENSION PASSED')
