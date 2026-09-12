"""Read-only checks on the supplied rig: hand curl, wing mechanisms and export."""

from pathlib import Path
import importlib, os, tempfile
from mathutils import Matrix, Quaternion, Vector
from types import SimpleNamespace

fixture = Path(__file__).with_name('test_addon_registration_blender.py')
exec(
    compile(
        fixture.read_text().split('addon_utils.disable(MODULE')[0], str(fixture), 'exec'
    )
)
reference = Path(
    os.environ.get('SUB_REFERENCE_BLEND', Path.home() / 'Downloads/Untitled3.blend')
)
if not reference.exists():
    print('SKIP reference rig: supply SUB_REFERENCE_BLEND')
    raise SystemExit(0)
bpy.ops.wm.open_mainfile(filepath=str(reference), use_scripts=False)
fingers = importlib.import_module(MODULE + '.source.extras.finger_sliders')
rig_export = importlib.import_module(MODULE + '.source.extras.rig_export')
export = importlib.import_module(MODULE + '.source.anim.export_anim')
obj = next(
    o
    for o in bpy.context.scene.objects
    if o.type == 'ARMATURE' and 'wing_spread_slider' in o.pose.bones
)
# Repair runs once on file load; author edits only in this disposable process.
assert obj['sub_finger_curl_version'] == 2
bpy.context.view_layer.objects.active = obj
obj.hide_set(False)
obj.select_set(True)
bpy.ops.object.mode_set(mode='POSE')
for side, digits, suffix in fingers.iter_hand_slots(obj):
    frame = fingers._hand_slider_frame(obj.data, side, suffix, digits)
    up = frame[3]
    for digit in (1, 2, 3, 4):
        for segment, bone, name in fingers._finger_chain(
            obj.data, side, digit, suffix, digits
        ):
            if segment == 0:
                continue
            pb = obj.pose.bones[name]
            axis = pb.get('sub_finger_curl_axis')
            weight = pb.get('sub_finger_curl_weight')
            if axis is None:
                continue
            hinge = bone.matrix_local.to_3x3().col[int(axis)] * (
                1 if weight > 0 else -1
            )
            motion = hinge.cross((bone.tail_local - bone.head_local).normalized())
            assert motion.dot(-up) > 0, (side, name, motion, up)
    for segment, bone, name in fingers._finger_chain(obj.data, side, 5, suffix, digits):
        if segment > 1:
            assert obj.pose.bones[name].constraints.get('SUB Finger Side') is None
print('REFERENCE BOTH HANDS CURL PALMWARD; THUMB OPPOSITION BASE ONLY')
# Add a small control edit so the bake must include fingers and the custom wing rig.
obj.animation_data_create()
obj.animation_data.action = None
for frame in (1, 3):
    bpy.context.scene.frame_set(frame)
    for name in ('wing_back_ctrl', 'wing_02_ctrl'):
        pb = obj.pose.bones[name]
        pb.rotation_mode = 'XYZ'
        pb.rotation_euler.x = 0.12 * (frame - 1)
        pb.keyframe_insert('rotation_euler', frame=frame)
    for name in (
        'wing_spread_slider',
        'BL_Curl_L',
        'BL_Curl_R',
        'BL_Thumb_L',
        'BL_Thumb_R',
        'BL_EyeLook',
    ):
        pb = obj.pose.bones.get(name)
        if pb:
            pb.location.x = 0.03 * (frame - 1)
            pb.location.y = 0.03 * (frame - 1)
            pb.keyframe_insert('location', frame=frame)
names = rig_export.export_bone_names(obj)
assert 'wing_back_ctrl' not in names and 'wing_mch_D_01_r' not in names
expected = {}
eye = importlib.import_module(MODULE + '.source.extras.eye_rig')
expected_eyes = {}
for frame in range(1, 4):
    bpy.context.scene.frame_set(frame)
    bpy.context.view_layer.update()
    evaluated = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
    expected[frame] = {}
    expected_eyes[frame] = eye.compute_cv31(
        obj, obj.pose.bones[eye.EYE_CTRL_BONE], bpy.context.scene.sub_scene_properties
    )
    for name in names:
        pb = evaluated.pose.bones[name]
        matrix = (
            export.get_smash_transform(pb.parent.matrix.inverted_safe() @ pb.matrix)
            if pb.parent and pb.parent.name in names
            else export.get_smash_root_matrix(pb.matrix)
        )
        expected[frame][name] = Matrix.LocRotScale(*matrix.decompose())
original = obj.animation_data.action
material = obj.data.animation_data.action if obj.data.animation_data else None
num_actions = len(bpy.data.actions)
with tempfile.TemporaryDirectory() as directory:
    file = str(Path(directory) / 'wings.nuanmb')
    export.export_model_anim_fast(
        bpy.context,
        SimpleNamespace(report=lambda *a, **kw: None),
        obj,
        file,
        True,
        True,
        False,
        1,
        3,
    )
    anim = addon.dependencies.ssbh_data_py.anim_data.read_anim(file)
    nodes = next(g.nodes for g in anim.groups if g.group_type.name == 'Transform')
    material_nodes = next(
        g.nodes for g in anim.groups if g.group_type.name == 'Material'
    )
    checked_eyes = 0
    for node in material_nodes:
        if node.name not in eye.EYE_TRACKS:
            continue
        track = next((t for t in node.tracks if t.name == eye.CV31), None)
        if track is None:
            continue
        checked_eyes += 1
        for i, value in enumerate(track.values):
            left, right, vertical, pupil = expected_eyes[i + 1]
            assert abs(value[2] - (left if node.name == 'EyeL' else right)) < 1e-5
            assert abs(value[3] - vertical) < 1e-5
    assert checked_eyes == 2, 'Both eye material tracks must be baked'
    worst = 0
    for node in nodes:
        for i, value in enumerate(node.tracks[0].values):
            actual = Matrix.LocRotScale(
                Vector(value.translation),
                Quaternion((value.rotation[3], *value.rotation[:3])),
                Vector(value.scale),
            )
            error = max(
                abs(actual[r][c] - expected[i + 1][node.name][r][c])
                for r in range(4)
                for c in range(4)
            )
            worst = max(worst, error)
            assert error < 0.001, (node.name, i, error)
assert obj.animation_data.action == original
assert (obj.data.animation_data.action if obj.data.animation_data else None) == material
assert len(bpy.data.actions) == num_actions
print('REFERENCE WING/FINGER/IK EXPORT PASSED', len(nodes), 'bones', worst)
