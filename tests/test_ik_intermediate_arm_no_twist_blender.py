from pathlib import Path

fixture = Path(__file__).with_name('test_addon_registration_blender.py')
exec(compile(fixture.read_text().split('floor = importlib.import_module')[0], str(fixture), 'exec'))
ik = importlib.import_module(MODULE + '.source.extras.ik_channels')
rig = importlib.import_module(MODULE + '.source.extras.create_animation_rig')
data = bpy.data.armatures.new('MultiBoneArms')
obj = bpy.data.objects.new('MultiBoneArms', data)
bpy.context.scene.collection.objects.link(obj)
bpy.context.view_layer.objects.active = obj
obj.select_set(True)
bpy.ops.object.mode_set(mode='EDIT')
parts = ['Shoulder'] + ['Shoulder' + str(i) for i in range(1, 6)]
parts += ['Arm'] + ['Arm' + str(i) for i in range(1, 6)] + ['Wrist', 'Hand']
for side, sign in (('L', 1), ('R', -1)):
    parent = None
    for index, part in enumerate(parts):
        bone = data.edit_bones.new(part + side)
        x = 2 + index * .56
        y = -.7 + min(index, 3) * .1
        if part == 'Hand':
            x, y = 8.9, 0
        bone.head = (sign * x, y, 11)
        bone.tail = (sign * (x + (3.5 if part in ('Shoulder', 'Arm') else 1)), y, 11)
        bone.align_roll((0, 0, -sign))
        bone.parent = parent
        parent = bone
bpy.ops.object.mode_set(mode='POSE')
original = {bone.name: bone.matrix_local.copy() for bone in data.bones}
assert ik.create_controls(bpy.context, obj, 'ARMS') == 2
rig._set_ik_enabled(bpy.context, obj, True, limbs='ARMS')
for side in ('L', 'R'):
    names = ('Shoulder' + side, 'Arm' + side, 'Hand' + side)
    solve = ik.solve_bone(obj, names).constraints['SUB IK Solve']
    assert solve.chain_count == len(parts) - 1
    # The single IK constraint lives on the chain's end bone.
    assert ik.solve_bone(obj, names).name == ik.PREFIX + 'Hand' + side
    path = ik.limb_path(obj, names)
    for parent, child in zip(path, path[1:]):
        assert data.bones[ik.PREFIX + child].parent.name == ik.PREFIX + parent
    helpers = [name for name in path[1:-2] if name != 'Arm' + side]
    for stretch in (False, True):
        data.sub_ik_stretch_arms = stretch
        control = obj.pose.bones['HandIK' + side]
        origin = control.matrix.copy()
        bpy.context.view_layer.update()
        evaluated = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
        reference = {}
        for name in helpers:
            bone = evaluated.pose.bones[ik.PREFIX + name]
            reference[name] = (bone.parent.matrix.inverted_safe() @ bone.matrix).to_quaternion()
        changes = {name: 0.0 for name in helpers}
        for step in range(1, 81):
            matrix = origin.copy()
            matrix.translation.x += (-1 if side == 'L' else 1) * step * .035
            control.matrix = matrix
            obj.update_tag()
            bpy.context.view_layer.update()
            evaluated = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
            for name in helpers:
                bone = evaluated.pose.bones[ik.PREFIX + name]
                relative = (bone.parent.matrix.inverted_safe() @ bone.matrix).to_quaternion()
                changes[name] = max(changes[name], reference[name].rotation_difference(relative).angle)
            for name in ik.limb_path(obj, names)[:-1]:
                rest = original[name].to_3x3()
                actual = evaluated.pose.bones[name].matrix.to_3x3()
                swing = rest.col[1].rotation_difference(actual.col[1])
                alignment = (swing @ rest.col[2]).normalized().dot(actual.col[2].normalized())
                assert alignment > .9, (side, stretch, step, name, alignment)
        assert all(angle > 1e-4 for angle in changes.values()), (side, stretch, changes)
        for full_chain_stretch in (False, True):
            data.sub_ik_stretch_chain_arms = full_chain_stretch
            for step in range(1, 31):
                matrix = origin.copy()
                matrix.translation.x += (1 if side == 'L' else -1) * (1 + step * .1)
                control.matrix = matrix
                obj.update_tag()
                bpy.context.view_layer.update()
                evaluated = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
                # Overreaching points the whole arm at the hand control. The solver keeps
                # the FK rest exactly (so matching is 1:1), and these joints are offset,
                # so the bones themselves need not be collinear.
                root = evaluated.pose.bones[ik.PREFIX + path[0]].head
                goal = evaluated.pose.bones['HandIK' + side].head
                for prefix in ('', ik.PREFIX):
                    # Blender's IK aims the wrist's tail; Stretch then carries the hand onto the control.
                    end = (evaluated.pose.bones[path[-1]].head if stretch and not prefix
                           else evaluated.pose.bones[prefix + path[-2]].tail)
                    miss = (end - root).angle(goal - root)
                    assert miss < .02, (side, stretch, full_chain_stretch, step, prefix, miss)
        control.matrix = origin
        obj.update_tag()
        bpy.context.view_layer.update()
for name, matrix in original.items():
    assert data.bones[name].matrix_local == matrix, name
print('14-BONE ARMS PRESERVE ALL ORIGINAL BONES AND AVOID AXIAL FLIPS WITH STRETCH OFF/ON PASSED')
