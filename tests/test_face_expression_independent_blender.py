from pathlib import Path
fixture=Path(__file__).with_name('test_face_components_blender.py')
exec(compile(fixture.read_text(encoding='utf-8-sig').split('# Removing face controllers')[0],str(fixture),'exec'))
from types import SimpleNamespace
lids=obj.pose.bones[cc.control_name(obj,editor.components[0])]
mouth=obj.pose.bones[cc.control_name(obj,editor.components[1])]
class Layout:
    def __init__(self): self.entries=[]
    def operator(self,*args,**kwargs):
        item=SimpleNamespace(**kwargs)
        self.entries.append(item)
        return item
for pb,expected in ((lids,{'None','Left Closed','Right Closed'}),(mouth,{'None','Smile'})):
    menu=SimpleNamespace(layout=Layout())
    face.SUB_MT_face_expression.draw(menu,SimpleNamespace(sub_expression_control=pb))
    assert {e.text for e in menu.layout.entries}==expected
    assert all(e.bone==pb.name for e in menu.layout.entries)
bpy.context.scene.frame_set(1)
assert bpy.ops.sub.face_expression_select(armature=obj.name,bone=lids.name,value=1)=={'FINISHED'}
assert bpy.ops.sub.face_expression_select(armature=obj.name,bone=mouth.name,value=1)=={'FINISHED'}
assert bpy.ops.sub.face_expression_select(armature=obj.name,bone=lids.name,value=2)=={'FINISHED'}
assert face.expression_get(mouth)==1 and face.expression_get(lids)==2
for pb in (lids,mouth):
    pb.sub_face_strength=1.5
    assert pb.sub_face_strength==1 and abs(pb.location.y-1)<1e-6
    pb.sub_face_strength=-.5
    assert pb.sub_face_strength==0 and abs(pb.location.y)<1e-6
    for f,value in ((1,0.0),(3,1.0)):
        face.strength_set(pb,value)
        pb.keyframe_insert('location',index=1,frame=f)
    assert bpy.ops.sub.face_expression_select(armature=obj.name,bone=pb.name,key_only=True)=={'FINISHED'}
bpy.context.scene.frame_set(1)
assert lids.location.y==0 and mouth.location.y==0
bpy.context.scene.frame_set(3)
assert lids.location.y==1 and mouth.location.y==1
print('INDEPENDENT COMPONENT MENUS AND KEYED 0-1 STRENGTH PASSED')

# Once keyed, menu choices must replace/add expression keys instead of snapping
# back to the evaluated old value, including with Auto Key disabled.
bpy.context.scene.tool_settings.use_keyframe_insert_auto=False
bpy.context.scene.frame_set(1)
assert bpy.ops.sub.face_expression_select(armature=obj.name,bone=lids.name,value=1)=={'FINISHED'}
assert bpy.ops.sub.face_expression_select(armature=obj.name,bone=lids.name,key_only=True)=={'FINISHED'}
bpy.context.scene.frame_set(5)
assert bpy.ops.sub.face_expression_select(armature=obj.name,bone=lids.name,value=2)=={'FINISHED'}
assert face.expression_get(lids)==2
bpy.context.scene.frame_set(1)
assert face.expression_get(lids)==1
bpy.context.scene.frame_set(5)
assert face.expression_get(lids)==2
assert bpy.ops.sub.face_expression_select(armature=obj.name,bone=lids.name,value=0)=={'FINISHED'}
assert face.expression_get(lids)==0
print('KEYED EXPRESSION MENU CAN SWITCH AND REPLACE KEYS PASSED')

assert bpy.ops.sub.face_expression_select(armature=obj.name,bone=mouth.name,key_strength=True)=={'FINISHED'}
curves=importlib.import_module(MODULE+'.source.anim.fcurve_compat')
assert any(fc.data_path==mouth.path_from_id()+'.location' and fc.array_index==1 for fc in curves.get_fcurves_for_assigned_slot(obj))
print('EXPRESSION AND STRENGTH EXPLICIT CURVE CREATION PASSED')

from importlib import import_module
compat=import_module(MODULE+'.source.blender_compat')
compat.assign_action(obj.animation_data,bpy.data.actions.new('Empty expression key test'))
edit=bpy.context.preferences.edit
available=getattr(edit,'use_keyframe_insert_available',None)
if available is not None: edit.use_keyframe_insert_available=True
try:
    assert bpy.ops.sub.face_expression_select(armature=obj.name,bone=mouth.name,key_only=True)=={'FINISHED'}
    assert bpy.ops.sub.face_expression_select(armature=obj.name,bone=mouth.name,key_strength=True)=={'FINISHED'}
    paths={fc.data_path for fc in curves.get_fcurves_for_assigned_slot(obj)}
    assert mouth.path_from_id()+'.sub_face_expression' in paths
    assert mouth.path_from_id()+'.location' in paths
finally:
    if available is not None: edit.use_keyframe_insert_available=available
print('EMPTY ACTION FIRST EXPRESSION AND STRENGTH KEYS PASSED')

# UI button properties must not inherit key-strength flags on later selections.
class ButtonLayout:
    def __init__(self):
        self.buttons=[]
        self.pointers=[]
        self.props=[]
    def row(self,**kwargs): return self
    def context_pointer_set(self,name,value):
        self.pointers.append((name,value))
    def menu(self,*args,**kwargs): pass
    def prop(self,data,prop,**kwargs):
        self.props.append((data,prop))
    def operator(self,*args,**kwargs):
        button=SimpleNamespace(key_only=True,key_strength=True)
        self.buttons.append(button)
        return button
layout=ButtonLayout()
face.draw_expression_control(layout,mouth)
assert layout.buttons[0].key_only and not layout.buttons[0].key_strength
assert layout.buttons[1].key_strength and not layout.buttons[1].key_only
assert (mouth,'sub_face_strength') in layout.props
assert ('pose_bone',mouth) in layout.pointers
assert ('active_pose_bone',mouth) in layout.pointers
menu=SimpleNamespace(layout=ButtonLayout())
face.SUB_MT_face_expression.draw(menu,SimpleNamespace(sub_expression_control=lids))
assert all(not b.key_only and not b.key_strength for b in menu.layout.buttons)
for name in ('key_only','key_strength'):
    assert bpy.ops.sub.face_expression_select.get_rna_type().properties[name].is_skip_save
print('EXPRESSION BUTTON FLAGS ARE ISOLATED PASSED')
