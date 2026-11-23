from pathlib import Path

fixture = Path(__file__).with_name('test_addon_registration_blender.py')
exec(compile(fixture.read_text().split('floor = importlib.import_module')[0], str(fixture), 'exec'))
mapper = importlib.import_module(MODULE + '.source.retargeting.nearest_bone_mapper')


def make_rig(name, prefix):
    data = bpy.data.armatures.new(name)
    obj = bpy.data.objects.new(name, data)
    bpy.context.collection.objects.link(obj)
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    bpy.ops.object.mode_set(mode='EDIT')
    for index, part in enumerate(('hips', 'arm', 'leg', 'finger', 'extra')):
        bone = data.edit_bones.new(prefix + part)
        bone.head, bone.tail = (index * 3, 0, 0), (index * 3, 1, 0)
    if prefix == 'dst_':
        data.edit_bones[prefix + 'leg'].tail.y = 3
        helper = data.edit_bones.new('nearby_leg_helper')
        helper.head, helper.tail = (6.01, 0, 0), (6.01, 3, 0)
    bpy.ops.object.mode_set(mode='OBJECT')
    obj.select_set(False)
    return obj


reference = make_rig('Category Reference', 'ref_')
target = make_rig('Category Target', 'dst_')
ref = reference.data.expykit_retarget
dst = target.data.expykit_retarget
ref.spine.hips = 'ref_hips'
ref.left_arm.arm = 'ref_arm'
ref.left_arm_ik.arm = 'ref_arm'
ref.left_leg.upleg = 'ref_leg'
ref.left_fingers.index.a = 'ref_finger'
for identifier, name in (('old_arm', 'ref_arm'), ('old_leg', 'ref_leg'), ('extra', 'ref_extra')):
    ref.custom.add_bone(identifier, name)
# A previous run left the same semantic arm in Custom, pointing at another bone.
dst.custom.add_bone('old_arm', 'dst_extra')
dst.custom.add_bone('old_leg', 'dst_leg')
for _ in range(2):
    mapped, custom = mapper.map_bones_by_proximity(reference, target)
    assert mapped == 5, mapped
    assert custom == 1, custom
    assert dst.spine.hips == 'dst_hips'
    assert dst.left_arm.arm == dst.left_arm_ik.arm == 'dst_arm'
    assert dst.left_leg.upleg == 'dst_leg'
    assert dst.left_fingers.index.a == 'dst_finger'
    assert dst.custom.get_bones() == [('extra', 'dst_extra')], dst.custom.get_bones()
# Old Custom aliases must never override category bindings, even before remapping.
ref.custom.add_bone('bad_arm', 'ref_arm')
dst.custom.add_bone('bad_arm', 'dst_extra')
ref.custom.add_bone('extra', 'ref_extra')
dst.custom.add_bone('extra', 'dst_extra')
setattr(ref.custom, 'extra', '')
setattr(dst.custom, 'extra', '')
presets = importlib.import_module(MODULE + '.expy_kit.preset_handler')
pairs = presets.get_settings_skel(ref).conversion_map(presets.get_settings_skel(dst))
assert pairs['ref_arm'] == 'dst_arm', pairs
assert pairs['ref_extra'] == 'dst_extra', pairs
# A categorized bone with no close match must not fall back to Custom.
bpy.context.view_layer.objects.active = target
target.select_set(True)
bpy.ops.object.mode_set(mode='EDIT')
for name in ('dst_leg',):
    bone = target.data.edit_bones[name]
    bone.head.x += 100
    bone.tail.x += 100
bpy.ops.object.mode_set(mode='OBJECT')
mapper.map_bones_by_proximity(reference, target, radius_scale=0.1)
assert all(identifier != 'old_leg' for identifier, _ in dst.custom.get_bones())
print('EXPY PROXIMITY CATEGORIES PASSED')
