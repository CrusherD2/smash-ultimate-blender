from pathlib import Path
from types import SimpleNamespace

fixture = Path(__file__).with_name('test_addon_registration_blender.py')
exec(compile(fixture.read_text().split('floor = importlib.import_module')[0], str(fixture), 'exec'))
ui = importlib.import_module(MODULE + '.expy_kit.ui')
compat = importlib.import_module(MODULE + '.source.blender_compat')
data = bpy.data.armatures.new('Selected Custom')
obj = bpy.data.objects.new('Selected Custom', data)
bpy.context.collection.objects.link(obj)
bpy.context.view_layer.objects.active = obj
obj.select_set(True)
bpy.ops.object.mode_set(mode='EDIT')
for index, name in enumerate(('Bone.One', 'Bone Two', 'Bone-Three')):
    bone = data.edit_bones.new(name)
    bone.head, bone.tail = (index, 0, 0), (index, 1, 0)
bpy.ops.object.mode_set(mode='POSE')
for bone in obj.pose.bones:
    compat.set_pose_bone_select(bone, True)
data.bones.active = data.bones['Bone.One']


class Layout:
    def __init__(self):
        self.labels = []

    def row(self, **kwargs):
        return self

    def label(self, **kwargs):
        pass

    def operator(self, name, **kwargs):
        self.labels.append(kwargs.get('text'))
        return SimpleNamespace()


layout = Layout()
ui.VIEW3D_PT_expy_retarget_custom.draw(SimpleNamespace(layout=layout), bpy.context)
assert 'Add Selected Bones' in layout.labels
assert bpy.ops.object.expy_kit_add_custom_bone('INVOKE_DEFAULT') == {'FINISHED'}
custom = data.expykit_retarget.custom
assert dict(custom.get_bones()) == {
    'bone_one': 'Bone.One', 'bone_two': 'Bone Two', 'bone_three': 'Bone-Three',
}
for identifier, _ in list(custom.get_bones()):
    custom.remove_bone(identifier)
for bone in obj.pose.bones:
    compat.set_pose_bone_select(bone, bone.name == 'Bone.One')
layout = Layout()
ui.VIEW3D_PT_expy_retarget_custom.draw(SimpleNamespace(layout=layout), bpy.context)
assert 'Add Active Bone' in layout.labels
assert bpy.ops.object.expy_kit_add_custom_bone(identifier='Chosen Name') == {'FINISHED'}
assert custom.get_bones() == [('chosen_name', 'Bone.One')]
print('EXPY ADD SELECTED CUSTOM BONES PASSED')
