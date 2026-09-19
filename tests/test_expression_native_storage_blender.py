from pathlib import Path
fixture=Path(__file__).with_name('test_face_expression_checkpoints_blender.py')
exec(compile(fixture.read_text(encoding='utf-8-sig').split('raw=importlib')[0],str(fixture),'exec'))
assert bpy.types.PoseBone.bl_rna.properties['sub_face_expression'].type=='INT'
# Exercise the edit/pose transitions from the crash log with live face drivers.
for i in range(25):
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.object.mode_set(mode='POSE')
    face.expression_set(obj.pose.bones[cc.control_name(obj,c)],3)
    bpy.context.scene.frame_set(1)
    bpy.context.view_layer.update()
print('NATIVE EXPRESSION STORAGE AND 25 EDIT-POSE CYCLES PASSED')
