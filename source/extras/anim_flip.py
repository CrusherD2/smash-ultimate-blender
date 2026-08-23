"""
Studio SB anim_flip convention, shared by Mirror Animation and Idle Pose Library.

The reference Maya .anim script does all of the following in Smash / Maya space:
  1. Negate translateZ
  2. Negate rotateX / rotateY (Smash quaternion X/Y)
  3. Leave translateX/Y, rotateZ, and scale unchanged
  4. Swap L/R bone-name suffixes, including numbered ones (FingerL11)

This must be applied to Smash-space TRS, then converted with the same
import path as idle poses (root Y-up, child get_blender_transform).
Negating Blender fcurve location/quaternion channels is not equivalent.
"""

import math
import os
import re

from mathutils import Matrix, Quaternion, Vector

from ..model.import_model import get_blender_transform

# Smash / nuanmb quaternion storage is (x, y, z, w).
_LR_SUFFIX = re.compile(r'^(.*)([LR])(\d*)$')
_POSE_BONE_PATH_DOUBLE = re.compile(r'^(pose\.bones\[")([^"]+)("\].*)$')
_POSE_BONE_PATH_SINGLE = re.compile(r"^(pose\.bones\[')([^']+)('\].*)$")


def flip_smash_translation(translation):
    """Negate Maya / Smash translateZ."""
    flipped = list(translation)
    flipped[2] = -flipped[2]
    return flipped


def flip_smash_rotation_xyzw(rotation):
    """Negate Smash quaternion X and Y (equivalent to Maya rotateX / rotateY)."""
    flipped = list(rotation)
    flipped[0] = -flipped[0]
    flipped[1] = -flipped[1]
    return flipped


def _root_basis_matrices():
    y_up_to_z_up = Matrix.Rotation(math.radians(90), 4, 'X')
    x_major_to_y_major = Matrix.Rotation(math.radians(-90), 4, 'Z')
    return y_up_to_z_up, x_major_to_y_major


def _smash_from_blender_rel(blender_rel):
    """Inverse of get_blender_transform for a child-bone relative matrix."""
    p = Matrix((
        (0, 1, 0, 0),
        (-1, 0, 0, 0),
        (0, 0, 1, 0),
        (0, 0, 0, 1),
    ))
    return p @ blender_rel @ p.inverted()


def smash_trs_from_pose_bone(bone):
    """
    Recover Smash-space translation / quaternion(x,y,z,w) / scale from a posed bone.
    Inverse of apply_smash_node_to_bone / animation import.
    """
    if bone.parent is None:
        y_up_to_z_up, x_major_to_y_major = _root_basis_matrices()
        raw = y_up_to_z_up.inverted() @ bone.matrix @ x_major_to_y_major.inverted()
    else:
        blender_rel = bone.parent.matrix.inverted() @ bone.matrix
        raw = _smash_from_blender_rel(blender_rel)
    translation, quat, scale = raw.decompose()
    return (
        [translation.x, translation.y, translation.z],
        [quat.x, quat.y, quat.z, quat.w],
        [scale.x, scale.y, scale.z],
    )


def smash_pose_data_from_armature(armature, bone_filter=None):
    pose_data = {}
    for bone in armature.pose.bones:
        if bone_filter is not None and bone.name not in bone_filter:
            continue
        translation, rotation, scale = smash_trs_from_pose_bone(bone)
        pose_data[bone.name] = {
            "translation": translation,
            "rotation": rotation,
            "scale": scale,
            "flags": {
                "override_translation": True,
                "override_rotation": True,
                "override_scale": True,
            },
        }
    return pose_data


def apply_smash_node_to_bone(bone, node_data):
    """Apply Smash-space TRS the same way animation import / idle poses do."""
    translation = Vector(node_data["translation"])
    tm = Matrix.Translation(translation)
    rotation = Quaternion((
        node_data["rotation"][3],
        node_data["rotation"][0],
        node_data["rotation"][1],
        node_data["rotation"][2],
    ))
    rm = Matrix.Rotation(rotation.angle, 4, rotation.axis)
    scale = Vector(node_data["scale"])
    sm = Matrix.Diagonal((scale[0], scale[1], scale[2], 1.0))
    raw_matrix = tm @ rm @ sm

    if bone.parent is None:
        y_up_to_z_up, x_major_to_y_major = _root_basis_matrices()
        bone.matrix = y_up_to_z_up @ raw_matrix @ x_major_to_y_major
    else:
        bone.matrix = bone.parent.matrix @ get_blender_transform(raw_matrix).transposed()


def _hierarchy_order(armature):
    roots = [bone for bone in armature.pose.bones if bone.parent is None]
    ordered = []
    for root in roots:
        ordered.append(root)
        ordered.extend(root.children_recursive)
    return ordered


def apply_smash_pose_data(armature, pose_data, target_bones=None, skip_bones=None):
    skip_bones = skip_bones or set()
    applied = []
    for bone in _hierarchy_order(armature):
        if bone.name not in pose_data or bone.name in skip_bones:
            continue
        if target_bones is not None and bone.name not in target_bones:
            continue
        apply_smash_node_to_bone(bone, pose_data[bone.name])
        applied.append(bone)
    return applied


def keyframe_pose_bones(bones, frame):
    for bone in bones:
        bone.keyframe_insert(data_path="location", frame=frame, group=bone.name)
        if bone.rotation_mode == 'QUATERNION':
            bone.keyframe_insert(data_path="rotation_quaternion", frame=frame, group=bone.name)
        else:
            bone.keyframe_insert(data_path="rotation_euler", frame=frame, group=bone.name)
        bone.keyframe_insert(data_path="scale", frame=frame, group=bone.name)


def swap_lr_bone_name(name):
    """
    Swap a Smash Ultimate L/R suffix the way Studio SB anim_flip does.

    ArmL → ArmR, FingerL11 → FingerR11, ClavicleR → ClavicleL.
    Names without an uppercase L/R suffix (Hip, Trans, Null) are unchanged.
    """
    match = _LR_SUFFIX.match(name)
    if not match:
        return name
    prefix, side, digits = match.group(1), match.group(2), match.group(3)
    new_side = 'R' if side == 'L' else 'L'
    return f'{prefix}{new_side}{digits}'


def _split_pose_path(name):
    """Split pose.bones[\"ArmL\"] into (prefix, bone_name, suffix)."""
    match = _POSE_BONE_PATH_DOUBLE.match(name)
    if match:
        return match.group(1), match.group(2), match.group(3)
    match = _POSE_BONE_PATH_SINGLE.match(name)
    if match:
        return match.group(1), match.group(2), match.group(3)
    return '', name, ''


def _difference(a, b):
    common_prefix = os.path.commonprefix((a, b))
    common_suffix = os.path.commonprefix((a[::-1], b[::-1]))[::-1]
    return a[len(common_prefix):len(a) - len(common_suffix)], b[len(common_prefix):len(b) - len(common_suffix)]


def _lower_tuple(words):
    return tuple(word.lower() for word in words)


def create_mirror_map(names, patterns=None):
    """
    Map each name to its L/R counterpart. Unpaired (center) names map to themselves
    so they still receive anim_flip channel negation.

    Accepts either raw bone names or fcurve prefixes like pose.bones[\"ArmL\"].
    """
    names = list(names)
    wrappers = {name: _split_pose_path(name) for name in names}
    unique_bones = {bone for _prefix, bone, _suffix in wrappers.values()}
    bone_map = {}

    # Pass 1: Studio SB suffix swap (R <-> L, R11 <-> L11)
    for bone in unique_bones:
        swapped = swap_lr_bone_name(bone)
        if swapped != bone and swapped in unique_bones:
            bone_map[bone] = swapped

    # Pass 2: leftover Left/Right word pairs
    if patterns is None:
        patterns = (
            ('l', 'r'),
            ('left', 'right'),
            ('L', 'R'),
            ('Left', 'Right'),
        )
    norm_patterns = tuple(_lower_tuple(_difference(*pattern)) for pattern in patterns)
    rpatterns = tuple(pattern[::-1] for pattern in norm_patterns)

    unmatched = [bone for bone in unique_bones if bone not in bone_map]
    for left_name in unmatched:
        for other in unique_bones:
            if left_name == other:
                continue
            if _lower_tuple(_difference(left_name, other)) in (*norm_patterns, *rpatterns):
                bone_map[left_name] = other
                break

    for bone in unique_bones:
        if bone not in bone_map:
            bone_map[bone] = bone

    mirror_map = {}
    for name in names:
        prefix, bone, suffix = wrappers[name]
        target = bone_map.get(bone, bone)
        mirror_map[name] = f'{prefix}{target}{suffix}'
    return mirror_map


def extract_bone_name_from_path(path):
    """Extract Hip from pose.bones[\"Hip\"] or a full data_path."""
    _prefix, bone, _suffix = _split_pose_path(path)
    if bone and bone != path:
        return bone
    if 'pose.bones[' in path:
        if '"' in path:
            return path.split('"')[1]
        if "'" in path:
            return path.split("'")[1]
    return ""


def should_exclude_bone_from_mirroring(bone_name, armature=None, include_fingers=True):
    """Optional UX filters. Hip / Trans / root are never excluded."""
    if not bone_name:
        return False

    bone_name_lower = bone_name.lower()
    if bone_name_lower in ('hip', 'hipn', 'trans', 'root', 'pelvis'):
        return False

    if bone_name.startswith('S_'):
        return True

    facial_keywords = ('brow', 'lip', 'eye', 'nose', 'cheek', 'jaw', 'mouth')
    if any(keyword in bone_name_lower for keyword in facial_keywords):
        return True

    if not include_fingers and bone_name.startswith('Finger'):
        return True

    if bone_name == 'Face':
        return True

    if armature is not None and getattr(armature, 'type', None) == 'ARMATURE':
        pose_bones = getattr(getattr(armature, 'pose', None), 'bones', None)
        if pose_bones is not None and bone_name in pose_bones:
            bone = pose_bones[bone_name]
            if bone.parent and bone.parent.name == 'Face':
                return True

    return False


def collect_excluded_bone_names(armature, include_fingers=True):
    if armature is None or getattr(armature, 'type', None) != 'ARMATURE':
        return set()
    return {
        bone.name
        for bone in armature.pose.bones
        if should_exclude_bone_from_mirroring(bone.name, armature, include_fingers)
    }


def mirror_smash_pose_data(pose_data, excluded_bones=None):
    """
    Apply anim_flip to Smash-space pose dicts used by the idle pose library.

    Each value is a dict with translation [x,y,z], rotation [x,y,z,w],
    optional scale, and flags. Hip / Trans are flipped like every other bone.
    """
    excluded_bones = excluded_bones or set()
    mirrored = {}
    for bone_name, data in pose_data.items():
        if bone_name in excluded_bones:
            mirrored[bone_name] = data
            continue
        target_name = swap_lr_bone_name(bone_name)
        flipped = dict(data)
        if "translation" in flipped:
            flipped["translation"] = flip_smash_translation(flipped["translation"])
        if "rotation" in flipped:
            flipped["rotation"] = flip_smash_rotation_xyzw(flipped["rotation"])
        mirrored[target_name] = flipped
    return mirrored


def mirror_evaluated_pose(armature, excluded_bones=None, target_bones=None):
    """
    Mirror the current evaluated pose in Smash space, then write it back
    with the same conversion idle poses use.
    """
    excluded_bones = excluded_bones or set()
    pose_data = smash_pose_data_from_armature(armature)
    pose_data = mirror_smash_pose_data(pose_data, excluded_bones=excluded_bones)
    return apply_smash_pose_data(
        armature,
        pose_data,
        target_bones=target_bones,
        skip_bones=excluded_bones,
    )
