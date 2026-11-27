from pathlib import Path

fixture = Path(__file__).with_name('test_addon_registration_blender.py')
exec(compile(fixture.read_text().split('floor = importlib.import_module')[0], str(fixture), 'exec'))

ops = importlib.import_module(MODULE + '.expy_kit.operators')


def armature(name, bones):
    data = bpy.data.armatures.new(name)
    obj = bpy.data.objects.new(name, data)
    bpy.context.collection.objects.link(obj)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.mode_set(mode='EDIT')
    for bone_name in bones:
        bone = data.edit_bones.new(bone_name)
        bone.head, bone.tail = (0, 0, 0), (0, 1, 0)
    bpy.ops.object.mode_set(mode='OBJECT')
    return obj


target = armature('Retarget Target', ['root', 'root_RET'])
source = armature('Retarget Source', ['root'])
other = armature('Unrelated', ['root'])
# Constraints without a target (Limit Location) must not break the search
other.pose.bones['root'].constraints.new('LIMIT_LOCATION')
source.pose.bones['root'].constraints.new('LIMIT_LOCATION')
copy = source.pose.bones['root'].constraints.new('COPY_TRANSFORMS')
copy.target, copy.subtarget = target, 'root_RET'
assert ops.find_retarget_source_armature(target) == source
assert ops.resolve_bake_armature_pair(target) == (source, target)
print('EXPY RETARGET SOURCE PASSED')
