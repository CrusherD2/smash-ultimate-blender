from pathlib import Path

fixture = Path(__file__).with_name('test_addon_registration_blender.py')
exec(compile(fixture.read_text().split('floor = importlib.import_module')[0], str(fixture), 'exec'))
ik = importlib.import_module(MODULE + '.source.extras.ik_channels')
if '--' in sys.argv:
    bpy.ops.wm.open_mainfile(filepath=sys.argv[sys.argv.index('--') + 1])
    obj = next(o for o in bpy.data.objects if o.type == 'ARMATURE')
else:
    data = bpy.data.armatures.new('Hip continuity')
    obj = bpy.data.objects.new('Hip continuity', data)
    bpy.context.collection.objects.link(obj)
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    bpy.ops.object.mode_set(mode='EDIT')
    hip = data.edit_bones.new('Hip')
    hip.head, hip.tail = (0, 0, 4), (0, 0, 5)
    for side, sign in (('L', 1), ('R', -1)):
        for parts, points in (
            (('Leg', 'Knee', 'Foot'), ((sign, 0, 4), (sign, .3, 2), (sign, 0, 0), (sign, -1, 0))),
            (('Shoulder', 'Arm', 'Hand'), ((sign, 0, 6), (sign * 3, .2, 6), (sign * 5, 0, 6), (sign * 6, 0, 6))),
        ):
            parent = hip
            for index, part in enumerate(parts):
                bone = data.edit_bones.new(part + side)
                bone.head, bone.tail, bone.parent = points[index], points[index + 1], parent
                parent = bone
    bpy.ops.object.mode_set(mode='POSE')
    for name in ('KneeL', 'KneeR', 'ArmL', 'ArmR'):
        bone = obj.pose.bones[name]
        bone.rotation_mode = 'XYZ'
        bone.rotation_euler.x = .7
        bone.rotation_euler.y = .35
        bone.keyframe_insert('rotation_euler', frame=1)
    bpy.context.scene.frame_set(1)

bpy.context.view_layer.update()
names = [name for name in ('ShoulderL', 'ArmL', 'HandL', 'ShoulderR', 'ArmR', 'HandR',
                          'LegL', 'KneeL', 'FootL', 'LegR', 'KneeR', 'FootR') if name in obj.pose.bones]
original = {name: obj.pose.bones[name].matrix.copy() for name in names}
assert ik.create_controls(bpy.context, obj) == 4
for name, matrix in original.items():
    error = max(abs(a - b) for row, wanted in zip(obj.pose.bones[name].matrix, matrix)
                for a, b in zip(row, wanted))
    assert error < 2e-4, (name, error)
hip = obj.pose.bones['Hip']
origin = hip.location.copy()
for axis in range(3):
    for shift in (-3.5, -.5, 0, .5, 3.5):
        hip.location = origin
        hip.location[axis] += shift
        obj.update_tag()
        bpy.context.view_layer.update()
        for _, chain, _, _ in ik.chains(obj):
            for first, second in zip(chain, chain[1:]):
                gap = (obj.pose.bones[first].tail - obj.pose.bones[second].head).length
                assert gap < 2e-3, (axis, shift, first, second, gap)
print('IK HIP CONTINUITY AND INITIAL ANIMATED POSE PASSED')
