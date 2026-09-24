from pathlib import Path
fixture = Path(__file__).with_name('test_addon_registration_blender.py')
exec(compile(fixture.read_text(encoding='utf-8').split('addon_utils.disable(MODULE')[0], str(fixture), 'exec'))
from mathutils import Matrix, Quaternion
flip = importlib.import_module(MODULE + '.source.extras.anim_flip')
mirror = importlib.import_module(MODULE + '.source.extras.mirror_animation')

# Extra bones whose rest axes do not follow the Smash convention: rolled,
# pointing sideways, and pairs whose two sides are not rest-symmetric.
BONES = [
    ('Trans', (0, 0, 0), (0, 0, 1), 0),
    ('Wing.L', (1, -2, 3), (1.5, -3, 3.2), .4),
    ('Wing.R', (1, 2, 3), (1.5, 3, 3.2), -.4),
    ('HornL', (.3, -.5, 5), (.3, -.5, 6), .9),
    ('HornR', (.3, .5, 5), (.3, .5, 6), .9),
    ('Tail', (-1, 0, 2), (-2.5, 0, 2.2), .6),
]
PAIRS = [('Wing.L', 'Wing.R'), ('Wing.R', 'Wing.L'), ('HornL', 'HornR'),
         ('HornR', 'HornL'), ('Tail', 'Tail')]
H = Matrix.Diagonal((1, -1, 1, 1))


def build():
    if bpy.context.object and bpy.context.object.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)
    for act in list(bpy.data.actions):
        bpy.data.actions.remove(act)
    bpy.ops.object.armature_add()
    obj = bpy.context.object
    bpy.ops.object.mode_set(mode='EDIT')
    obj.data.edit_bones.remove(obj.data.edit_bones[0])
    for name, head, tail, roll in BONES:
        bone = obj.data.edit_bones.new(name)
        bone.head, bone.tail, bone.roll = head, tail, roll
    bpy.ops.object.mode_set(mode='POSE')
    for frame in (1, 5, 9):
        for i, (name, *_rest) in enumerate(BONES):
            bone = obj.pose.bones[name]
            bone.rotation_mode = 'QUATERNION'
            bone.location = (.1 * i + .02 * frame, .05 * frame * (i + 1), .03 * i - .01 * frame)
            bone.rotation_quaternion = Quaternion((1, .03 * frame + .1 * i, .02 * i - .1, .05 * frame)).normalized()
            flip.keyframe_pose_bones([bone], frame)
    return obj


def sample(obj):
    out = {}
    for frame in (1, 5, 9):
        bpy.context.scene.frame_set(frame)
        out[frame] = {p.name: p.matrix_basis.copy() for p in obj.pose.bones}
    return out


def change(obj, src, dst):
    a = obj.data.bones[src].matrix_local.to_3x3().normalized().to_4x4()
    b = obj.data.bones[dst].matrix_local.to_3x3().normalized().to_4x4()
    return b.inverted() @ H @ a


def error(a, b):
    return max(abs(a[r][c] - b[r][c]) for r in range(4) for c in range(4))


def check(obj, source, pairs, frames=(1, 5, 9), label=''):
    for frame in frames:
        bpy.context.scene.frame_set(frame)
        for src, dst in pairs:
            c = change(obj, src, dst)
            expected = c @ source[frame][src] @ c.inverted()
            got = obj.pose.bones[dst].matrix_basis
            assert error(got, expected) < 1e-4, (label, frame, src, dst, error(got, expected))


def run(axis='Y', **kwargs):
    obj = bpy.context.object
    ok, _ = mirror.apply_mirror_to_action(bpy.context, obj, obj.animation_data.action, axis, **kwargs)
    assert ok


# Face bones are matched by whole name words, not by stray letters.
for name in ('UpperLip', 'LipU', 'left_upper_eyelid_a_01', 'EyebrowL', 'Tongue_offset', 'Jaw'):
    assert flip.is_face_bone_name(name) and flip.should_exclude_bone_from_mirroring(name), name
for name in ('balloon_rope_blue_flip', 'HairClipL', 'Tulip', 'Hip'):
    assert not flip.is_face_bone_name(name) and not flip.should_exclude_bone_from_mirroring(name), name

# Default Y mirror (Smash Y Anim Flip off) must mirror extra bones in rest space.
obj = build()
source = sample(obj)
run(smash_y_anim_flip=False, include_fingers=True)
check(obj, source, PAIRS, label='fcurve Y')

# The Smash Y path must agree.
obj = build()
source = sample(obj)
run(smash_y_anim_flip=True, include_fingers=True)
check(obj, source, PAIRS, label='smash Y')

# Selected bones only mirrors in place.
obj = build()
source = sample(obj)
run(smash_y_anim_flip=False, selected_bones_only=True, selected_bone_names={'Wing.L', 'Tail'})
check(obj, source, [('Wing.L', 'Wing.L'), ('Tail', 'Tail')], label='selected')
bpy.context.scene.frame_set(5)
assert error(obj.pose.bones['Wing.R'].matrix_basis, source[5]['Wing.R']) < 1e-6

# Only active frame changes just that frame.
obj = build()
source = sample(obj)
bpy.context.scene.frame_set(5)
run(smash_y_anim_flip=False, only_active_frame=True)
check(obj, source, PAIRS, frames=(5,), label='active frame')
bpy.context.scene.frame_set(9)
assert error(obj.pose.bones['Wing.R'].matrix_basis, source[9]['Wing.R']) < 1e-6

# A one-sided animation mirrors onto the unanimated side and clears the source.
obj = build()
action = obj.animation_data.action
for fc in [fc for fc in mirror.get_fcurves(action) if '"HornR"' in fc.data_path]:
    mirror.remove_fcurve(action, fc)
obj.pose.bones['HornR'].matrix_basis = Matrix.Identity(4)
source = sample(obj)
run(smash_y_anim_flip=False)
check(obj, source, [('HornL', 'HornR'), ('HornR', 'HornL')], label='one sided')

# Scanning for custom bones lists them checked, so scanning never silently
# stops them from mirroring.
assert bpy.ops.sub.find_custom_mirror_bones() == {'FINISHED'}
items = bpy.context.scene.sub_scene_properties.mirror_custom_bones
assert {i.name for i in items} == {'Wing.L', 'Wing.R', 'HornL', 'HornR', 'Tail'}
assert all(i.include for i in items)
# Unchecked bones are left alone.
obj = build()
items['Tail'].include = False
source = sample(obj)
run(smash_y_anim_flip=False)
check(obj, source, PAIRS[:4], label='unchecked')
bpy.context.scene.frame_set(5)
assert error(obj.pose.bones['Tail'].matrix_basis, source[5]['Tail']) < 1e-6
items.clear()

# Extra bones under Smash bones. Smash bones flip their local Z, so a Hip
# pointing along armature X mirrors the whole pose across armature X. Extra
# children must land exactly on the reflection of their source, whatever
# their own rest axes (the tail used to swing down through the floor).
from mathutils import Vector


def frame_matrix(head, y_axis, z_axis):
    y = Vector(y_axis).normalized()
    z = Vector(z_axis)
    z = (z - y * z.dot(y)).normalized()
    m = Matrix((y.cross(z), y, z)).transposed().to_4x4()
    m.translation = head
    return m


D = Matrix.Diagonal((1, 1, -1, 1))
RX = Matrix.Diagonal((-1, 1, 1, 1))
hip = frame_matrix((0, 0, 10), (0, -1, -.3), (1, 0, 0))
leg_l = frame_matrix((2, 0, 9), (.3, -.2, -1), (.5, .8, .2))
SMASH = [
    ('Hip', None, hip),
    ('LegL', 'Hip', leg_l),
    ('LegR', 'Hip', RX @ leg_l @ D),
    ('Tail1', 'Hip', frame_matrix((0, 2, 8), (0, .95, -.3), (1, 0, 0))),
    ('Tail2', 'Tail1', frame_matrix((0, 4, 7.4), (.2, .9, -.3), (1, .1, 0))),
    ('BulbL', 'Hip', frame_matrix((2, 1, 9.5), (0, 0, 1), (1, 0, 0))),
    ('BulbR', 'Hip', frame_matrix((-2, 1, 9.5), (0, 0, 1), (1, 0, 0))),
    ('LeafL', 'LegL', frame_matrix((2.5, 0, 7), (0, .7, .7), (1, 0, 0))),
    ('LeafR', 'LegR', frame_matrix((-2.5, 0, 7), (0, .7, .7), (1, 0, 0))),
    # Swing chains: a centre chain and a pair whose rests are not mirrored.
    ('S_Tail1', 'Hip', frame_matrix((0, 2.5, 9), (0, .9, -.4), (1, 0, 0))),
    ('S_Tail2', 'S_Tail1', frame_matrix((0, 4, 8.3), (.1, .9, -.3), (1, 0, .2))),
    ('S_Hair_L1', 'Hip', frame_matrix((1, -1, 11), (.3, 0, 1), (0, 1, 0))),
    ('S_Hair_R1', 'Hip', frame_matrix((-1, -1, 11), (-.1, .2, 1), (0, 1, 0))),
    ('S_Hair_L2_null', 'S_Hair_L1', frame_matrix((1.3, -1, 12), (0, 0, 1), (1, 0, 0))),
    ('S_Hair_R2_null', 'S_Hair_R1', frame_matrix((-1.3, -1, 12), (0, 0, 1), (1, 0, 0))),
    # Only one side's name carries a marker (Amy's Hammer / HammerR); an
    # off-centre bone whose R means red has no twin and stays in place.
    ('Hammer', 'LegL', frame_matrix((2.2, -.5, 8), (0, -1, 0), (1, 0, 0))),
    ('HammerR', 'LegR', frame_matrix((-2.2, -.5, 8), (0, -1, 0), (1, 0, 0))),
    ('EmeraldR', 'Hip', frame_matrix((1.5, 1, 10), (0, 0, 1), (1, 0, 0))),
    ('EmeraldB', 'Hip', frame_matrix((-1.5, 1.3, 10), (0, 0, 1), (1, 0, 0))),
    # Face rig: compound lip names are only recognisable by sitting under Face.
    ('Face', 'Hip', frame_matrix((0, -1, 12), (0, 0, 1), (1, 0, 0))),
    ('Mouth_group', 'Face', frame_matrix((0, -1.5, 12), (0, -1, 0), (1, 0, 0))),
    ('DownlipL', 'Mouth_group', frame_matrix((.3, -1.8, 12), (0, -1, 0), (1, 0, 0))),
    ('DownlipR', 'Mouth_group', frame_matrix((-.3, -1.8, 12), (0, -1, 0), (1, 0, 0))),
    # Parentless IK controls with identical (not mirrored) axes on both sides.
    ('FootIKL', None, frame_matrix((2, -1, 1), (0, 0, 1), (1, 0, 0))),
    ('FootIKR', None, frame_matrix((-2, -1, 1), (0, 0, 1), (1, 0, 0))),
    ('ToeIKL', 'FootIKL', frame_matrix((2, -2, .5), (0, -1, 0), (0, 0, 1))),
    ('ToeIKR', 'FootIKR', frame_matrix((-2, -2, .5), (0, -1, 0), (0, 0, 1))),
]


def build_smash():
    if bpy.context.object and bpy.context.object.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)
    for act in list(bpy.data.actions):
        bpy.data.actions.remove(act)
    bpy.ops.object.armature_add()
    obj = bpy.context.object
    bpy.ops.object.mode_set(mode='EDIT')
    obj.data.edit_bones.remove(obj.data.edit_bones[0])
    for name, parent, matrix in SMASH:
        bone = obj.data.edit_bones.new(name)
        bone.head, bone.tail = (0, 0, 0), (0, 1, 0)
        bone.matrix = matrix
        if parent:
            bone.parent = obj.data.edit_bones[parent]
    bpy.ops.object.mode_set(mode='POSE')
    for frame in (1, 5, 9):
        for i, (name, *_rest) in enumerate(SMASH):
            bone = obj.pose.bones[name]
            bone.rotation_mode = 'QUATERNION'
            bone.location = (.1 * i - .02 * frame, .03 * frame, .05 * i + .02 * frame)
            bone.rotation_quaternion = Quaternion((1, .04 * frame - .05 * i, .1 + .02 * i, .03 * frame)).normalized()
            flip.keyframe_pose_bones([bone], frame)
    return obj


obj = build_smash()
custom_mirror = importlib.import_module(MODULE + '.source.extras.mirror_custom_bones')
pairs = custom_mirror.control_mirror_map(obj)
assert pairs['Hammer'] == 'HammerR' and pairs['HammerR'] == 'Hammer'
assert pairs['EmeraldR'] == 'EmeraldR' and pairs['EmeraldB'] == 'EmeraldB'
for name in ('Face', 'Mouth_group', 'DownlipL'):
    assert flip.should_exclude_bone_from_mirroring(name, obj), name
    assert name not in flip.find_custom_mirror_bones(obj), name
assert not flip.should_exclude_bone_from_mirroring('Tail1', obj)
bpy.context.scene.frame_set(5)
face_before = obj.pose.bones['DownlipL'].matrix_basis.copy()
posed_before = {}
for frame in (1, 5, 9):
    bpy.context.scene.frame_set(frame)
    posed_before[frame] = {p.name: p.matrix.copy() for p in obj.pose.bones}
run(smash_y_anim_flip=False, include_fingers=True)
bpy.context.scene.frame_set(5)
assert error(obj.pose.bones['DownlipL'].matrix_basis, face_before) < 1e-6
for frame in (1, 5, 9):
    bpy.context.scene.frame_set(frame)
    for src, dst in [('Hip', 'Hip'), ('LegL', 'LegR'), ('Tail1', 'Tail1'), ('Tail2', 'Tail2'),
                     ('BulbL', 'BulbR'), ('BulbR', 'BulbL'), ('LeafL', 'LeafR'), ('LeafR', 'LeafL'),
                     ('FootIKL', 'FootIKR'), ('FootIKR', 'FootIKL'), ('ToeIKL', 'ToeIKR'),
                     ('S_Tail1', 'S_Tail1'), ('S_Tail2', 'S_Tail2'), ('S_Hair_L1', 'S_Hair_R1'),
                     ('S_Hair_R1', 'S_Hair_L1'), ('S_Hair_L2_null', 'S_Hair_R2_null'),
                     ('Hammer', 'HammerR'), ('HammerR', 'Hammer')]:
        a = obj.data.bones[src].matrix_local
        b = obj.data.bones[dst].matrix_local
        fix = b.to_3x3().normalized().to_4x4().inverted() @ RX @ a.to_3x3().normalized().to_4x4()
        expected = RX @ posed_before[frame][src] @ fix.inverted()
        got = obj.pose.bones[dst].matrix
        assert error(got, expected) < 1e-4, ('smash parent', frame, src, dst, error(got, expected))

# IK controls are listed by Find Custom Bones, and unchecking them keeps them
# in place on both mirror paths.
for smash_y in (False, True):
    obj = build_smash()
    assert bpy.ops.sub.find_custom_mirror_bones() == {'FINISHED'}
    items = bpy.context.scene.sub_scene_properties.mirror_custom_bones
    assert {'FootIKL', 'FootIKR', 'ToeIKL', 'S_Tail1', 'S_Hair_L1'} <= {i.name for i in items}
    for name in ('FootIKL', 'FootIKR', 'S_Tail1'):
        items[name].include = False
    bpy.context.scene.frame_set(5)
    held = {n: obj.pose.bones[n].matrix_basis.copy() for n in ('FootIKL', 'FootIKR', 'S_Tail1')}
    run(smash_y_anim_flip=smash_y, include_fingers=True)
    bpy.context.scene.frame_set(5)
    for name, basis in held.items():
        assert error(obj.pose.bones[name].matrix_basis, basis) < 1e-6, (smash_y, name)
    items.clear()
print('MIRROR CUSTOM FCURVE TEST PASSED')
