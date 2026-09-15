"""Independent IK solve bones. Original bones retain their editable FK action.

Only the output Copy Transforms constraints blend; the IK solver always runs at
full influence on a separate chain. Matching samples FK before writing IK keys.
"""
import math
import json
import uuid
import re
import os
import sys
import time
from contextlib import contextmanager, nullcontext
import bpy
from mathutils import Matrix, Vector

from . import pose_math

PREFIX = 'BL_SUB_IK_'
PULL_PREFIX = 'BL_SUB_IK_PULL_'
CORRECTION_PREFIX = 'BL_SUB_IK_MATCH_'
OUTPUT = 'SUB IK Blend'
VERSION = 'sub_independent_ik'
MATCH_KEY = 'sub_ik_channel_matches'
END_ROTATION = 'SUB IK End Rotation'
END_SCALE = 'SUB IK End Scale'
END_LOCATION = 'SUB IK Stretch'
TOE_OUTPUT = 'SUB IK Toe'
PULL_TARGET = 'SUB IK Pull Target'
PULL_END = 'SUB IK Pull End'
ARM_PULL_PROPERTY = 'sub_ik_arm_pull'


def connected_toe_bones(obj, names):
    """Parented toe hierarchy; Smash joints need not use Blender Connected."""
    foot = names[-1]
    if not foot.startswith('Foot'):
        return ()
    wanted = ('Toe' + foot[4:]).lower()
    root = next((bone for bone in obj.data.bones if bone.name.lower() == wanted), None)
    if root is None:
        return ()
    result = [root.name]
    pending = list(root.children)
    while pending:
        bone = pending.pop(0)
        if 'toe' in bone.name.lower():
            result.append(bone.name)
        pending.extend(bone.children)
    return tuple(result)


def toe_pivot_name(obj, names):
    """Ground the deepest toe descendant, with a stable name tie-break for branches."""
    toe_names = connected_toe_bones(obj, names)
    if not toe_names:
        return None
    root = obj.data.bones[toe_names[0]]

    def depth(name):
        bone, count = obj.data.bones[name], 0
        while bone != root:
            bone, count = bone.parent, count + 1
        return count

    return min(toe_names, key=lambda name: (-depth(name), name.lower(), name))


def foot_controls(names, obj=None):
    """Reverse-foot controls for a leg chain, or ``None`` for an arm."""
    foot = names[-1]
    if not foot.startswith('Foot'):
        return None
    suffix = foot[4:]
    toe_name = 'Toe' + suffix
    if obj is not None:
        toe_name = toe_pivot_name(obj, names) or toe_name
    return 'FootRollIK' + suffix, 'ToeIK' + suffix, PREFIX + 'FootTarget' + suffix, toe_name


def toe_articulation(obj, names):
    """Independent proximal toe bend for a multi-joint toe chain."""
    toes = connected_toe_bones(obj, names)
    if not toes or toes[0] == toe_pivot_name(obj, names):
        return None
    suffix = names[-1][4:]
    return 'ToeBendIK' + suffix, PREFIX + 'ToeBasis' + suffix, toes[0]


def endpoint_target(obj, names, fallback):
    controls = foot_controls(names, obj)
    return controls[2] if controls and controls[2] in obj.pose.bones else fallback


def end_constraints(end):
    return [c for c in end.constraints
            if c.name in {END_ROTATION, END_SCALE, END_LOCATION}]


def wire_end_controls(obj):
    """Repair old endpoint transforms without rebuilding or rematching the rig."""
    from .create_animation_rig import _ensure_constraint_influence_driver
    for kind, names, target, _ in chains(obj):
        endpoint = endpoint_target(obj, names, target)
        end = obj.pose.bones.get(PREFIX + names[-1])
        if end is None:
            continue
        for con in list(end.constraints):
            if con.type == 'COPY_TRANSFORMS' and con.target == obj and con.subtarget == target:
                con.driver_remove('influence')
                end.constraints.remove(con)
        for name, type_ in ((END_ROTATION, 'COPY_ROTATION'),
                            (END_SCALE, 'COPY_SCALE'),
                            (END_LOCATION, 'COPY_LOCATION')):
            con = end.constraints.get(name)
            if con is None:
                con = end.constraints.new(type_)
                con.name = name
                con.target_space = con.owner_space = 'WORLD'
            con.target = obj
            con.subtarget = endpoint
            if name == END_LOCATION:
                _endpoint_stretch_driver(obj, con, kind)


def limb_path(obj, names):
    """Actual parent path, including twist/offset bones between named joints."""
    path = []
    bone = obj.data.bones.get(names[-1])
    while bone is not None:
        path.append(bone.name)
        if bone.name == names[0]:
            path.reverse()
            return tuple(path) if names[1] in path else ()
        bone = bone.parent
    return ()


def chain_path(obj, root, end, middle=None):
    """Return the parent path from root to end, optionally through middle."""
    path = []
    bone = obj.data.bones.get(end)
    while bone is not None:
        path.append(bone.name)
        if bone.name == root:
            path.reverse()
            if len(path) >= 3 and (middle is None or middle in path[1:-1]):
                return tuple(path)
            return ()
        bone = bone.parent
    return ()


def custom_jobs(obj):
    try:
        records = json.loads(obj.get('sub_custom_ik_chains', '[]'))
    except (ValueError, TypeError):
        return
    for record in records:
        try:
            names = chain_path(obj, record['root'], record['end'], record['middle'])
            job = record['kind'], names, record['target'], record['pole']
        except (KeyError, TypeError):
            continue
        if names:
            yield job


def bend_name(obj, names):
    try:
        records = json.loads(obj.get('sub_custom_ik_chains', '[]'))
    except (ValueError, TypeError):
        records = []
    for record in records:
        if record.get('root') == names[0] and record.get('end') == names[-1]:
            return record.get('middle', names[len(names) // 2])
    match = re.fullmatch(r'(Leg|Shoulder)([LR]\d*(?:\.\d{3})*)', names[0])
    if match:
        candidate = ('Knee' if match[1] == 'Leg' else 'Arm') + match[2]
        if candidate in names:
            return candidate
    return names[len(names) // 2]


def arm_pull_value(obj, pole):
    pole_bone = obj.pose.bones.get(pole)
    return float(getattr(pole_bone.bone, ARM_PULL_PROPERTY, 0.0)) if pole_bone else 0.0


def solve_bone(obj, names):
    return obj.pose.bones[PREFIX + limb_path(obj, names)[-2]]


def create_controls(context, obj, limbs='BOTH', custom_only=False, custom_targets=None):
    """One idempotent creation path for IK Tools and the Animation Rig."""
    from . import create_animation_rig as rig, anim_layers_compat
    rig._activate_armature(context, obj)
    jobs = []
    for b in (() if custom_only else obj.data.bones):
        bone_match = re.fullmatch(r'(Leg|Shoulder)([LR]\d*(?:\.\d{3})*)', b.name)
        if not bone_match:
            continue
        part, suffix = bone_match.groups()
        kind = 'LEGS' if part == 'Leg' else 'ARMS'
        if limbs not in (kind, 'BOTH'):
            continue
        names = tuple(p + suffix for p in (('Leg', 'Knee', 'Foot') if kind == 'LEGS' else ('Shoulder', 'Arm', 'Hand')))
        if all(n in obj.data.bones for n in names) and limb_path(obj, names):
            jobs.append((kind, names, ('FootIK' if kind == 'LEGS' else 'HandIK') + suffix,
                         ('KneeIK' if kind == 'LEGS' else 'ArmIK') + suffix))
    jobs.extend(job for job in custom_jobs(obj) if limbs in (job[0], 'BOTH')
                and (custom_targets is None or job[2] in custom_targets))
    # Existing controls may have user-authored dependencies or animation. Only
    # freshly generated controls are eligible for the independent fast path.
    fresh_controls = all(
        name not in obj.data.bones
        for _, names, target, pole in jobs
        for name in (*(PREFIX + n for n in names), target, pole)
    )
    with rig.defer_pose_tool_updates(), rig._disable_autokey(context), anim_layers_compat.anim_layers_paused():
        bpy.ops.object.mode_set(mode='EDIT')
        bones = obj.data.edit_bones
        for _, names, target, pole in jobs:
            root, mid, end = [bones[n] for n in (names[0], bend_name(obj, names), names[-1])]
            if target not in bones:
                control = bones.new(target)
                control.matrix = end.matrix.copy()
                control.length = max(end.length * 1.5, .1)
                control.parent = None
                control.use_deform = False
            if pole not in bones:
                axis = (end.head-root.head).normalized()
                bend = mid.head-root.head-axis*(mid.head-root.head).dot(axis)
                if bend.length < 1e-6:
                    bend = axis.orthogonal()
                control = bones.new(pole)
                control.head = mid.head + bend.normalized() * (root.length + mid.length)
                control.tail = control.head + Vector((0, max(mid.length*.25, .1), 0))
                control.parent = None
                control.use_deform = False
        bpy.ops.object.mode_set(mode='POSE')
        collection = obj.data.collections.get('IK Bones') or obj.data.collections.new('IK Bones')
        for _, _, target, pole in jobs:
            for n in (target, pole):
                collection.assign(obj.data.bones[n])
                obj.data.bones[n].color.palette = 'THEME01'
        if jobs:
            # Seed the new controls from the current FK pose before enabling IK.
            match(context, obj, limbs, entire=False, key=True, _batch=fresh_controls, _targets={job[2] for job in jobs})
            rig._key_use_ik(obj, context.scene.frame_current, limbs=limbs, enabled=True)
            rig._set_ik_enabled(context, obj, True, limbs=limbs)
            context.view_layer.update()
    # Animation-rig widgets stay on Create Animation Rig / Add IK. IK Tools
    # keeps octahedral bones unless this armature already has that rig.
    if rig.armature_has_animation_rig(obj):
        from .control_appearance import style_ik_controls
        style_ik_controls(context, obj)
    return len(jobs)


def _signature(obj, kind):
    return [obj.data.bones[PREFIX + names[0]].get('sub_ik_generation', '') + ':4'
            for _, names, _, _ in chains(obj, kind) if PREFIX + names[0] in obj.data.bones]


def mark_matched(obj, action, limbs):
    if action is None:
        return
    records = json.loads(action.get(MATCH_KEY, '{}'))
    for kind in ('ARMS', 'LEGS'):
        if limbs in (kind, 'BOTH'):
            signature = _signature(obj, kind)
            if signature:
                records[kind] = signature
    action[MATCH_KEY] = json.dumps(records)


def unmatched(obj, action):
    """A different action or recreated solver needs its own match."""
    try:
        records = json.loads(action.get(MATCH_KEY, '{}')) if action else {}
    except (ValueError, TypeError):
        records = {}
    return {kind for kind in ('ARMS', 'LEGS') if list(chains(obj, kind))
            and (not _signature(obj, kind) or records.get(kind) != _signature(obj, kind))}


def chains(obj, limbs='BOTH'):
    from .fk_to_ik import iter_leg_fk_chains, iter_arm_fk_chains
    if limbs in {'LEGS', 'BOTH'}:
        for c in iter_leg_fk_chains(obj):
            names = (c['leg'].name, c['knee'].name, c['foot'].name)
            if limb_path(obj, names):
                yield 'LEGS', names, c['foot_ik'].name, c['knee_ik'].name
    if limbs in {'ARMS', 'BOTH'}:
        for c in iter_arm_fk_chains(obj):
            if all(c[k] is not None for k in ('shoulder', 'arm', 'hand', 'hand_ik', 'arm_ik')):
                names = (c['shoulder'].name, c['arm'].name, c['hand'].name)
                if limb_path(obj, names):
                    yield 'ARMS', names, c['hand_ik'].name, c['arm_ik'].name
    for job in custom_jobs(obj):
        if limbs in (job[0], 'BOTH') and all(name in obj.pose.bones for name in job[2:]):
            yield job


def outputs(obj, limbs='BOTH'):
    for kind, names, target, pole in chains(obj, limbs):
        for name in limb_path(obj, names):
            pb = obj.pose.bones[name]
            con = pb.constraints.get(OUTPUT)
            if con is not None:
                yield pb, con, kind


def toe_outputs(obj, limbs='BOTH'):
    for kind, names, _target, _pole in chains(obj, limbs):
        controls = foot_controls(names, obj) if kind == 'LEGS' else None
        for name in connected_toe_bones(obj, names) if controls else ():
            toe = obj.pose.bones[name]
            con = toe.constraints.get(TOE_OUTPUT)
            if con:
                yield toe, con, kind


def ensure(obj, context, limbs='BOTH'):
    from . import create_animation_rig as rig
    jobs = list(chains(obj, limbs))
    if not jobs:
        return
    fresh = [j for j in jobs if any(PREFIX + n not in obj.data.bones for n in limb_path(obj, j[1]))]
    reverse_feet = [j for j in jobs
                    if j[0] == 'LEGS' and foot_controls(j[1], obj)
                    and foot_controls(j[1], obj)[3] in obj.data.bones]
    missing_reverse = [j for j in reverse_feet
                       if any(n not in obj.data.bones for n in foot_controls(j[1], obj)[:3])
                       or (toe_articulation(obj, j[1]) and any(n not in obj.data.bones for n in toe_articulation(obj, j[1])[:2]))
                       or any(pb.constraints.get(TOE_OUTPUT) and pb.name != foot_controls(j[1], obj)[3]
                              and not (toe_articulation(obj, j[1]) and pb.name == toe_articulation(obj, j[1])[2])
                              for pb in (obj.pose.bones[n] for n in connected_toe_bones(obj, j[1])))]
    misplaced_reverse = [j for j in reverse_feet if j not in missing_reverse
                         and not obj.data.bones[foot_controls(j[1], obj)[0]].get('sub_foot_pivot_space')]
    stale_articulation = [j for j in reverse_feet if toe_articulation(obj, j[1])
                          and (not obj.pose.bones[toe_articulation(obj, j[1])[2]].constraints.get(TOE_OUTPUT)
                               or obj.pose.bones[toe_articulation(obj, j[1])[2]].constraints[TOE_OUTPUT].subtarget != toe_articulation(obj, j[1])[1])]
    if fresh or missing_reverse or misplaced_reverse or stale_articulation:
        # Heal the old rest-hold workaround once, before installing independent chains.
        rig._clear_fk_rest_hold(obj)
        rig.unmute_all_ik_fk_fcurves(obj)
        bpy.ops.object.mode_set(mode='EDIT')
        bones = obj.data.edit_bones
        for kind, names, target, pole in fresh:
            path = limb_path(obj, names)
            for name in path:
                src = bones[name]
                dst = bones.get(PREFIX + name) or bones.new(PREFIX + name)
                dst.matrix = src.matrix.copy()
                dst.length = src.length
                dst.use_deform = False
                dst['sub_ik_generation'] = uuid.uuid4().hex
                dst.inherit_scale = src.inherit_scale
                dst.use_local_location = src.use_local_location
                dst.use_inherit_rotation = src.use_inherit_rotation
                parent = src.parent
                dst.parent = bones.get(PREFIX + parent.name) if parent and parent.name in path else parent
                dst.use_connect = src.use_connect
            # Controls must not inherit any FK limb rotation.
            for name in (target, pole):
                control = bones[name]
                matrix = control.matrix.copy()
                control.parent = None
                control.use_connect = False
                control.matrix = matrix
        for _kind, names, target, _pole in missing_reverse:
            roll_name, toe_name, output_name, original_toe = foot_controls(names, obj)
            foot = bones[target]
            toe = bones[original_toe]
            roll = bones.get(roll_name) or bones.new(roll_name)
            roll_length = max(foot.length * .45, .1)
            # Matching gives FootIK the FK foot's pose matrix, even when their
            # rest axes differ. Express the hinge in that same foot space.
            foot_space = foot.matrix @ bones[names[-1]].matrix.inverted_safe()
            roll.head = foot_space @ toe.head
            roll['sub_foot_pivot_space'] = 1
            roll.tail = roll.head + foot.vector.normalized() * roll_length
            roll.roll = foot.roll
            toe_control = bones.get(toe_name) or bones.new(toe_name)
            toe_control.head, toe_control.tail, toe_control.roll = toe.head, toe.tail, toe.roll
            output = bones.get(output_name) or bones.new(output_name)
            output.head, output.tail, output.roll = foot.head, foot.tail, foot.roll
            output.length = max(foot.length * .35, .1)
            for bone, parent in ((roll, foot), (toe_control, foot), (output, roll)):
                bone.parent = parent
                bone.use_connect = False
                bone.use_deform = False
            articulation = toe_articulation(obj, names)
            if articulation:
                bend_name_, basis_name, root_toe = articulation
                bend = bones.get(bend_name_) or bones.new(bend_name_)
                bend.head = foot_space @ bones[root_toe].head
                bend.tail = bend.head + foot.vector.normalized() * roll_length
                bend.roll = foot.roll
                bend.parent, bend.use_connect, bend.use_deform = roll, False, False
                basis = bones.get(basis_name) or bones.new(basis_name)
                basis.matrix = foot_space @ bones[root_toe].matrix
                basis.length = bones[root_toe].length
                basis.parent, basis.use_connect, basis.use_deform = roll, False, False
                output.parent = bend
        for _kind, names, target, _pole in misplaced_reverse:
            roll_name, _toe_name, output_name, original_toe = foot_controls(names, obj)
            roll = bones[roll_name]
            output_matrix = bones[output_name].matrix.copy()
            delta = (bones[target].matrix @ bones[names[-1]].matrix.inverted_safe()
                     @ bones[original_toe].head) - roll.head
            # Keep axes and keyed channels; repair only the hinge's rest offset.
            roll.translate(delta)
            bones[output_name].matrix = output_matrix
            roll['sub_foot_pivot_space'] = 1
        bpy.ops.object.mode_set(mode='POSE')
        collection = obj.data.collections.get('IK Internal') or obj.data.collections.new('IK Internal')
        collection.is_visible = False
        for kind, names, target, pole in fresh:
            path = limb_path(obj, names)
            for name in path:
                source = obj.pose.bones[name]
                solver = obj.pose.bones[PREFIX + name]
                for old in list(solver.constraints):
                    if old.name == 'SUB IK Solve':
                        solver.constraints.remove(old)
                old_output = source.constraints.get(OUTPUT)
                if old_output is not None:
                    old_output.driver_remove('influence')
                    source.constraints.remove(old_output)
                solver.rotation_mode = 'QUATERNION'
                solver.matrix_basis = source.matrix_basis.copy()
                collection.assign(solver.bone)
                # Remove only the old constraints owned by this limb's controls.
                for con in list(source.constraints):
                    if con.type in {'IK', 'COPY_ROTATION'} and con.target == obj and con.subtarget in (target, pole):
                        con.driver_remove('influence')
                        source.constraints.remove(con)
                for axis in 'xyz':
                    setattr(solver, 'lock_ik_' + axis, False)
                    setattr(solver, 'use_ik_limit_' + axis, False)
                solver.ik_stretch = 0.0
                con = source.constraints.new('COPY_TRANSFORMS')
                con.name = OUTPUT
                con.target = obj
                con.subtarget = solver.name
                con.target_space = con.owner_space = 'POSE'
            mid = solve_bone(obj, names)
            con = mid.constraints.new('IK')
            con.name = 'SUB IK Solve'
            con.target = con.pole_target = obj
            con.subtarget = target
            con.pole_subtarget = pole
            con.chain_count = len(path) - 1
            con.use_stretch = False
            con.iterations = 200
        controls_collection = obj.data.collections.get('IK Bones') or obj.data.collections.new('IK Bones')
        for _kind, names, _target, _pole in reverse_feet:
            roll_name, toe_name, output_name, original_toe = foot_controls(names, obj)
            if output_name not in obj.pose.bones:
                continue
            collection.assign(obj.data.bones[output_name])
            collection.is_visible = False
            for name in (roll_name, toe_name):
                controls_collection.assign(obj.data.bones[name])
                obj.data.bones[name].color.palette = 'THEME09' if name == roll_name else 'THEME01'
                pb = obj.pose.bones[name]
                pb.rotation_mode = 'XYZ'
                pb.lock_location = (True, True, True)
                pb.lock_scale = (True, True, True)
            articulation = toe_articulation(obj, names)
            for name in connected_toe_bones(obj, names):
                pb = obj.pose.bones[name]
                old = pb.constraints.get(TOE_OUTPUT)
                if old and name != original_toe and not (articulation and name == articulation[2]):
                    old.driver_remove('influence')
                    pb.constraints.remove(old)
            toe = obj.pose.bones.get(original_toe)
            if toe:
                con = toe.constraints.get(TOE_OUTPUT) or toe.constraints.new('COPY_ROTATION')
                con.name, con.target, con.subtarget = TOE_OUTPUT, obj, toe_name
                con.owner_space = con.target_space = 'WORLD'
                from .create_animation_rig import _ensure_constraint_influence_driver
                _ensure_constraint_influence_driver(obj, toe, con, 'sub_use_ik_legs')
            if articulation:
                bend_name_, basis_name, root_toe = articulation
                bend = obj.pose.bones[bend_name_]
                bend.rotation_mode = 'XYZ'
                bend.lock_location = bend.lock_scale = (True, True, True)
                controls_collection.assign(bend.bone)
                bend.bone.color.palette = 'THEME09'
                collection.assign(obj.data.bones[basis_name])
                root = obj.pose.bones[root_toe]
                con = root.constraints.get(TOE_OUTPUT) or root.constraints.new('COPY_ROTATION')
                con.name, con.target, con.subtarget = TOE_OUTPUT, obj, basis_name
                con.owner_space = con.target_space = 'WORLD'
                _ensure_constraint_influence_driver(obj, root, con, 'sub_use_ik_legs')
            mid = solve_bone(obj, names)
            solve = mid.constraints.get('SUB IK Solve')
            if solve and solve.target == obj:
                solve.subtarget = output_name
    paths = {name for _, names, _, _ in jobs for name in limb_path(obj, names)}
    missing_pull = [name for name in paths if PULL_PREFIX + name not in obj.data.bones]
    if missing_pull:
        bpy.ops.object.mode_set(mode='EDIT')
        bones = obj.data.edit_bones
        # Connected heads cannot translate. Parenting and rest transforms stay
        # intact, but the generated positional output must be allowed to move.
        for name in paths:
            bones[name].use_connect = False
        for name in missing_pull:
            src = bones[name]
            dst = bones.new(PULL_PREFIX + name)
            dst.matrix = src.matrix.copy()
            dst.length = src.length
            dst.use_deform = False
        bpy.ops.object.mode_set(mode='POSE')
        collection = obj.data.collections.get('IK Internal') or obj.data.collections.new('IK Internal')
        collection.is_visible = False
        for name in missing_pull:
            collection.assign(obj.data.bones[PULL_PREFIX + name])
    missing_corrections = [name for name in paths if CORRECTION_PREFIX + name not in obj.data.bones]
    if missing_corrections:
        bpy.ops.object.mode_set(mode='EDIT')
        bones = obj.data.edit_bones
        for name in missing_corrections:
            src = bones[PREFIX + name]
            dst = bones.new(CORRECTION_PREFIX + name)
            dst.matrix, dst.length = src.matrix.copy(), src.length
            dst.parent, dst.use_deform = src, False
        bpy.ops.object.mode_set(mode='POSE')
        collection = obj.data.collections.get('IK Internal') or obj.data.collections.new('IK Internal')
        collection.is_visible = False
        for name in missing_corrections:
            pb = obj.pose.bones[CORRECTION_PREFIX + name]
            pb.rotation_mode = 'QUATERNION'
            collection.assign(pb.bone)
    obj.data[VERSION] = 4
    wire(obj)
    from . import ik_floor_contact
    ik_floor_contact.restore_pending(context, obj)
    context.view_layer.update()


def wire(obj):
    from .create_animation_rig import _ensure_constraint_influence_driver, _limb_switch_prop
    wire_end_controls(obj)
    for kind, names, target, pole in chains(obj):
        path = limb_path(obj, names)
        for name in path[:-1]:
            solver = obj.pose.bones.get(PREFIX + name)
            if solver:
                solver.driver_remove('ik_stretch')
                solver.ik_stretch = 0.0
        solver = solve_bone(obj, names)
        solve = solver.constraints.get('SUB IK Solve') if solver else None
        if solve:
            solve.use_stretch = False
        distances = [0.0]
        for first, second in zip(path, path[1:]):
            distances.append(distances[-1] + (
                obj.data.bones[second].head_local - obj.data.bones[first].head_local).length)
        for index, name in enumerate(path):
            source = obj.pose.bones[name]
            pull = obj.pose.bones.get(PULL_PREFIX + name)
            blend = source.constraints.get(OUTPUT)
            if pull is None or blend is None:
                continue
            base = pull.constraints.get('SUB IK Pull Base') or pull.constraints.new('COPY_TRANSFORMS')
            base.name = 'SUB IK Pull Base'
            base.target, base.subtarget = obj, (CORRECTION_PREFIX + name if CORRECTION_PREFIX + name in obj.pose.bones else PREFIX + name)
            base.target_space = base.owner_space = 'POSE'
            blend.subtarget = pull.name
            _ensure_constraint_influence_driver(obj, source, blend, _limb_switch_prop(kind))
            blend.mute = False
            weight = distances[index] / distances[-1] if distances[-1] > 1e-8 else index / (len(path) - 1)
            for label, subtarget, sign in (
                    (PULL_TARGET, endpoint_target(obj, names, target), 1.0),
                    (PULL_END, PREFIX + path[-1], -1.0)):
                # A zero weight contributes nothing at any influence. Drop the
                # constraint and its driver instead of evaluating both per frame.
                if abs(weight) < 1e-8:
                    old = pull.constraints.get(label)
                    if old:
                        old.driver_remove('influence')
                        pull.constraints.remove(old)
                    continue
                con = pull.constraints.get(label) or pull.constraints.new('TRANSFORM')
                con.name = label
                con.target, con.subtarget = obj, subtarget
                con.target_space = con.owner_space = 'POSE'
                con.map_from = con.map_to = 'LOCATION'
                con.mix_mode = 'ADD'
                con.use_motion_extrapolate = True
                for axis in 'xyz':
                    setattr(con, 'from_min_' + axis, 0.0)
                    setattr(con, 'from_max_' + axis, 1.0)
                    setattr(con, 'to_min_' + axis, 0.0)
                    setattr(con, 'to_max_' + axis, sign * weight)
                _stretch_chain_driver(obj, con, kind, index == len(path) - 1)
                con.mute = False
    wire_arm_pulls(obj)
    for kind, names, target, _pole in chains(obj):
        path = limb_path(obj, names)
        distances = [0.0]
        for a, b in zip(path, path[1:]):
            distances.append(distances[-1] + (obj.data.bones[b].head_local - obj.data.bones[a].head_local).length)
        for index, name in enumerate(path[:-1]):
            pull = obj.pose.bones.get(PULL_PREFIX + name)
            if pull is None:
                continue
            con = pull.constraints.get('SUB IK Progressive Scale') or pull.constraints.new('COPY_SCALE')
            con.name = 'SUB IK Progressive Scale'
            con.target, con.subtarget = obj, endpoint_target(obj, names, target)
            con.target_space = con.owner_space = 'POSE'
            weight = distances[index] / distances[-1] if distances[-1] > 1e-8 else index / (len(path)-1)
            driver = con.driver_add('influence').driver
            driver.type = 'SCRIPTED'
            for var in list(driver.variables):
                driver.variables.remove(var)
            var = driver.variables.new()
            var.name, var.type = 'amount', 'SINGLE_PROP'
            var.targets[0].id_type = 'ARMATURE'
            var.targets[0].id = obj.data
            var.targets[0].data_path = 'sub_ik_progressive_scale_' + kind.lower()
            driver.expression = f'amount * {weight!r}'
    from . import ik_floor_contact
    ik_floor_contact.rewire(obj)


def _stretch_chain_driver(obj, constraint, kind, endpoint):
    driver = constraint.driver_add('influence').driver
    driver.type = 'SCRIPTED'
    for variable in list(driver.variables):
        driver.variables.remove(variable)
    props = [('stretch', 'sub_ik_stretch_' + kind.lower())]
    chain_prop = 'sub_ik_stretch_chain_' + kind.lower()
    if hasattr(obj.data, chain_prop):
        props.append(('chain', chain_prop))
    for variable_name, prop in props:
        variable = driver.variables.new()
        variable.name, variable.type = variable_name, 'SINGLE_PROP'
        variable.targets[0].id_type = 'ARMATURE'
        variable.targets[0].id = obj.data
        variable.targets[0].data_path = prop
    driver.expression = 'stretch' if endpoint else (
        'stretch * chain' if len(props) == 2 else '0')


def _endpoint_stretch_driver(obj, constraint, kind):
    """Keep endpoint-only stretch active when full-chain stretch is off."""
    driver = constraint.driver_add('influence').driver
    driver.type = 'SCRIPTED'
    for variable in list(driver.variables):
        driver.variables.remove(variable)
    props = [('stretch', 'sub_ik_stretch_' + kind.lower())]
    chain_prop = 'sub_ik_stretch_chain_' + kind.lower()
    if hasattr(obj.data, chain_prop):
        props.append(('chain', chain_prop))
    for variable_name, prop in props:
        variable = driver.variables.new()
        variable.name, variable.type = variable_name, 'SINGLE_PROP'
        variable.targets[0].id_type = 'ARMATURE'
        variable.targets[0].id = obj.data
        variable.targets[0].data_path = prop
    driver.expression = 'stretch * (1-chain)' if len(props) == 2 else 'stretch'


def _arm_pull_driver(obj, constraint, pole):
    driver = constraint.driver_add('influence').driver
    driver.type = 'SCRIPTED'
    for variable in list(driver.variables):
        driver.variables.remove(variable)
    for variable_name, id_type, target_id, data_path in (
            ('pull', 'ARMATURE', obj.data,
             obj.data.bones[pole].path_from_id() + '.' + ARM_PULL_PROPERTY),
            ('stretch', 'ARMATURE', obj.data, 'sub_ik_stretch_arms'),
            ('chain', 'ARMATURE', obj.data, 'sub_ik_stretch_chain_arms')):
        variable = driver.variables.new()
        variable.name, variable.type = variable_name, 'SINGLE_PROP'
        variable.targets[0].id_type = id_type
        variable.targets[0].id = target_id
        variable.targets[0].data_path = data_path
    driver.expression = 'pull * stretch * chain'


def wire_arm_pulls(obj):
    """Distribute each arm pole's independently controlled positional pull."""
    for _kind, names, target, pole in chains(obj, 'ARMS'):
        path = limb_path(obj, names)
        middle = bend_name(obj, names)
        if middle not in path or pole not in obj.pose.bones:
            continue
        bend_index = path.index(middle)
        distances = [0.0]
        for first, second in zip(path, path[1:]):
            distances.append(distances[-1] + (
                obj.data.bones[second].head_local - obj.data.bones[first].head_local).length)
        total, bend_distance = distances[-1], distances[bend_index]
        bend_fraction = bend_distance / total if total > 1e-8 else bend_index / (len(path) - 1)
        for index, name in enumerate(path):
            pull = obj.pose.bones.get(PULL_PREFIX + name)
            if pull is None:
                continue
            if index <= bend_index:
                u = distances[index] / bend_distance if bend_distance > 1e-8 else index / max(bend_index, 1)
            else:
                span = total - bend_distance
                u = (total - distances[index]) / span if span > 1e-8 else 0.0
            weight = u * u * (3.0 - 2.0 * u)
            terms = (
                ('Pole', pole, weight),
                ('Bend', PREFIX + middle, -weight),
                ('Hand', endpoint_target(obj, names, target), -weight * bend_fraction),
                ('End', PREFIX + path[-1], weight * bend_fraction),
            )
            for suffix, subtarget, factor in terms:
                label = 'SUB IK Arm Pull ' + suffix
                if abs(factor) < 1e-8:
                    old = pull.constraints.get(label)
                    if old:
                        old.driver_remove('influence')
                        pull.constraints.remove(old)
                    continue
                con = pull.constraints.get(label) or pull.constraints.new('TRANSFORM')
                con.name = label
                con.target, con.subtarget = obj, subtarget
                con.target_space = con.owner_space = 'POSE'
                con.map_from = con.map_to = 'LOCATION'
                con.mix_mode = 'ADD'
                con.use_motion_extrapolate = True
                for axis in 'xyz':
                    setattr(con, 'from_min_' + axis, 0.0)
                    setattr(con, 'from_max_' + axis, 1.0)
                    setattr(con, 'to_min_' + axis, 0.0)
                    setattr(con, 'to_max_' + axis, factor)
                _arm_pull_driver(obj, con, pole)
                con.mute = False


def upgrade_pull_controls(context, obj):
    """Add positional outputs to saved rigs without rematching their keys."""
    jobs = list(chains(obj))
    if not any(prefix + name not in obj.data.bones
               for _, names, _, _ in jobs for name in limb_path(obj, names)
               for prefix in (PULL_PREFIX, CORRECTION_PREFIX)):
        wire(obj)
        return
    from . import create_animation_rig as rig
    active = context.view_layer.objects.active
    selected = list(context.selected_objects)
    mode = active.mode if active else 'OBJECT'
    try:
        if active and mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        rig._activate_armature(context, obj)
        ensure(obj, context)
    finally:
        if context.object and context.object.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        for item in context.selected_objects:
            item.select_set(False)
        for item in selected:
            item.select_set(True)
        context.view_layer.objects.active = active
        if active and mode != 'OBJECT':
            bpy.ops.object.mode_set(mode=mode)


def _key(pb, frame, previous):
    from .fk_to_ik import _key_pose_bone
    if pb.rotation_mode == 'QUATERNION':
        q = pb.rotation_quaternion.copy()
        if pb.name in previous and q.dot(previous[pb.name]) < 0:
            q.negate()
            pb.rotation_quaternion = q
        previous[pb.name] = q
    _key_pose_bone(pb, frame)


def _angle(a, b, axis):
    a = a - axis * a.dot(axis)
    b = b - axis * b.dot(axis)
    if min(a.length, b.length) < 1e-8:
        return 0.0
    return math.atan2(axis.dot(a.cross(b)), a.dot(b))


def clean_animation(obj, limbs='BOTH', tolerance=1e-4):
    """Reduce baked transform curves, validating against the original at quarter frames.

    Keep endpoints, leave modifiers/discrete curves alone, and never touch switch
    curves or other limbs. Curves whose curvature needs Bezier handles are kept.
    """
    from ..anim.fcurve_compat import get_all_action_fcurves
    from .anim_layers_compat import viewport_driving_action
    from bisect import bisect_right
    action, _ = viewport_driving_action(obj)
    if action is None:
        return 0
    names = set()
    for _, group, target, pole in chains(obj, limbs):
        names.update(limb_path(obj, group))
        names.update(PREFIX + n for n in limb_path(obj, group))
        names.update((target, pole))
        controls = foot_controls(group, obj)
        if controls:
            names.update(controls[:3])
            articulation = toe_articulation(obj, group)
            if articulation:
                names.update(articulation[:2])
    paths = {obj.pose.bones[n].path_from_id() for n in names if n in obj.pose.bones}
    allowed = {path + '.' + channel for path in paths for channel in
               ('location', 'rotation_euler', 'rotation_quaternion', 'rotation_axis_angle', 'scale')}
    allowed.update(solve_bone(obj, group).constraints['SUB IK Solve'].path_from_id() + '.pole_angle'
                   for _, group, _, _ in chains(obj, limbs))
    removed = 0
    for fc in get_all_action_fcurves(action, id_type='OBJECT'):
        points = fc.keyframe_points
        if fc.data_path not in allowed or len(points) < 3 or fc.modifiers or fc.mute or fc.lock:
            continue
        if any(p.interpolation not in {'LINEAR', 'BEZIER'} for p in points):
            continue
        coords = [(float(p.co.x), float(p.co.y)) for p in points]
        if any(b[0] <= a[0] for a, b in zip(coords, coords[1:])):
            continue
        keep = {0, len(coords)-1}
        pending = [(0, len(coords)-1)]
        while pending:
            first, last = pending.pop()
            if last-first < 2:
                continue
            x0, y0 = coords[first]
            x1, y1 = coords[last]
            error, index = max((abs(coords[i][1] - (y0 + (y1-y0)*(coords[i][0]-x0)/(x1-x0))), i)
                               for i in range(first+1, last))
            if error > tolerance:
                keep.add(index)
                pending.extend(((first, index), (index, last)))
        if len(keep) == len(coords):
            continue
        reduced = [coords[i] for i in sorted(keep)]
        xs = [c[0] for c in reduced]
        # Include original key times as well as <= quarter-frame intervals.
        # Validate before mutating so rejected reductions leave keys/handles exact.
        valid = True
        for left, right in zip(coords, coords[1:]):
            count = max(4, math.ceil((right[0]-left[0])*4))
            for j in range(count+1):
                x = left[0] + (right[0]-left[0])*j/count
                i = min(max(bisect_right(xs, x)-1, 0), len(reduced)-2)
                x0, y0 = reduced[i]
                x1, y1 = reduced[i+1]
                y = y0 + (y1-y0)*(x-x0)/(x1-x0)
                if abs(fc.evaluate(x)-y) > tolerance:
                    valid = False
                    break
            if not valid:
                break
        if not valid:
            continue
        for i in reversed(range(len(coords))):
            if i not in keep:
                points.remove(points[i], fast=True)
                removed += 1
        for p in points:
            p.interpolation = 'LINEAR'
        fc.update()
    return removed


def _dependency_audit(obj, jobs, separate):
    """Owner map for the rig's dependency islands, or None if it is not closed.

    ``separate=True`` gives each selected chain its own island, which is what
    scheduling two limbs into one graph update requires. ``separate=False``
    puts every chain in one island, which is what isolating the rig into a
    temporary scene -- and hiding downstream meshes -- requires. Cross-limb
    sharing fails the first and is fine for the second; an external parent, an
    outside constraint target or a pose-reading driver fails both.

    `jobs` is intentionally unused: the audit always walks
    `chains(obj, 'BOTH')`, the whole rig, regardless of which chains were
    selected. Unselected limbs' solvers evaluate too, so narrowing this to
    the selected chains would weaken the guard, not simplify it.
    """
    from . import ik_match_diag as diag
    guard = 'batch' if separate else 'selfcontained'
    if obj.parent:
        return diag.reject(guard, 'object_parent')
    if obj.constraints:
        return diag.reject(guard, 'object_constraints')
    all_jobs = list(chains(obj, 'BOTH'))
    owners = {}
    muted_outputs = {con.as_pointer() for _, con, _ in
                     (*outputs(obj, 'BOTH'), *toe_outputs(obj, 'BOTH')) if con.mute}
    # Include unselected limbs: their solvers also evaluate, but do not make
    # otherwise independent selected chains unsafe to schedule together.
    for index, (_, names, target, pole) in enumerate(all_jobs):
        island = index if separate else 0
        path = limb_path(obj, names)
        # A mixed/legacy rig may have controls on an unselected limb without
        # the independent solver generation. Do not upgrade it just to batch.
        if any(PREFIX + name not in obj.pose.bones for name in path):
            return diag.reject(guard, 'legacy_controls')
        if solve_bone(obj, names).constraints.get('SUB IK Solve') is None:
            return diag.reject(guard, 'missing_solver')
        controls = foot_controls(names, obj)
        articulation = toe_articulation(obj, names)
        owned = [*path, *(PREFIX + n for n in path),
                 *(PULL_PREFIX + n for n in path), target, pole]
        if controls:
            owned.extend(controls)
        if articulation:
            owned.extend(articulation)
        for name in dict.fromkeys(owned):
            if name in owners and owners[name] != island:
                return diag.reject(guard, 'shared_bone')
            owners[name] = island
    # Descendants (fingers and toe tips, for example) belong to the same
    # dependency island. A separately owned descendant is checked below.
    for bone in obj.pose.bones:
        if bone.name in owners:
            continue
        parent = bone.parent
        while parent is not None and parent.name not in owners:
            parent = parent.parent
        if parent is not None:
            owners[bone.name] = owners[parent.name]
    props = {'sub_use_ik_arms', 'sub_use_ik_legs',
             'sub_ik_stretch_arms', 'sub_ik_stretch_legs',
             'sub_ik_stretch_chain_arms', 'sub_ik_stretch_chain_legs',
             'sub_ik_progressive_scale_arms', 'sub_ik_progressive_scale_legs'}
    props.update(obj.data.bones[pole].path_from_id() + '.' + ARM_PULL_PROPERTY
                 for kind, _, _, pole in chains(obj, 'ARMS'))
    if obj.data.animation_data and obj.data.animation_data.drivers:
        return diag.reject(guard, 'armature_data_driver')
    if obj.animation_data and obj.animation_data.action:
        from ..anim.fcurve_compat import get_all_action_fcurves
        pole_paths = {solve_bone(obj, names).constraints['SUB IK Solve'].path_from_id() + '.pole_angle'
                      for _, names, _, _ in all_jobs}
        for curve in get_all_action_fcurves(obj.animation_data.action, id_type='OBJECT'):
            # Animated constraint settings can change dependencies after the
            # initial check. Our own pole-angle keys only affect their own limb.
            if '.constraints[' in curve.data_path:
                if curve.data_path not in pole_paths:
                    return diag.reject(guard, 'animated_constraint')
    for curve in obj.animation_data.drivers if obj.animation_data else ():
        driver = curve.driver
        if not curve.data_path.endswith('.influence') or not driver.variables:
            return diag.reject(guard, 'pose_driver')
        # Only pure expressions emitted by our wiring helpers. All inputs are
        # armature properties, so none can read another chain's evaluated pose.
        expressions = {driver.variables[0].name, 'stretch * chain',
                       'stretch * (1-chain)', 'pull * stretch * chain', '0'}
        # 'SUB IK Progressive Scale' bakes each link's fraction of the chain
        # length into its own expression, so the text differs per bone and
        # cannot be enumerated the way the others are. Match the shape instead:
        # the driver variable scaled by one literal, nothing else. The input is
        # still a single armature property, checked against `props` below.
        progressive = re.fullmatch(re.escape(driver.variables[0].name)
                                   + r' \* -?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?',
                                   driver.expression)
        if driver.type != 'SCRIPTED' or not (
                driver.expression in expressions or progressive):
            return diag.reject(guard, 'foreign_driver_expression')
        for var in driver.variables:
            if (var.type != 'SINGLE_PROP' or var.targets[0].id != obj.data
                    or var.targets[0].data_path not in props):
                return diag.reject(guard, 'foreign_driver_input')
    for bone in obj.pose.bones:
        owner = owners.get(bone.name)
        if bone.parent and bone.parent.name in owners:
            if owner != owners[bone.parent.name]:
                return diag.reject(guard, 'cross_island_parent')
        for con in bone.constraints:
            # Only the output blends stay muted throughout matching. Check all
            # other constraints, including ones animated from muted to active.
            if con.as_pointer() in muted_outputs:
                continue
            if con.type not in {'COPY_TRANSFORMS', 'COPY_LOCATION', 'COPY_ROTATION',
                                'COPY_SCALE', 'DAMPED_TRACK', 'IK', 'TRANSFORM'}:
                return diag.reject(guard, 'unsupported_constraint')
            if getattr(con, 'use_bbone_shape', False):
                return diag.reject(guard, 'bbone_shape_constraint')
            if con.type == 'IK' and (owner is None or con.chain_count < 1):
                return diag.reject(guard, 'unowned_ik')
            if con.type == 'IK':
                ancestor = bone
                for _ in range(con.chain_count):
                    if ancestor is None or owners.get(ancestor.name) != owner:
                        return diag.reject(guard, 'ik_chain_crosses_island')
                    ancestor = ancestor.parent
            targets = [(con.target, con.subtarget)]
            if getattr(con, 'space_object', None) is not None:
                targets.append((con.space_object, con.space_subtarget))
            if con.type == 'IK':
                targets.append((con.pole_target, con.pole_subtarget))
            for target, name in targets:
                if target is None:
                    continue
                if target != obj or not name:
                    return diag.reject(guard, 'external_constraint_target')
                if name in owners and owners[name] != owner:
                    return diag.reject(guard, 'cross_island_constraint_target')
    diag.accept(guard)
    return owners


def _can_batch_match(obj, jobs):
    """Only combine evaluations when each limb reads independent pose inputs."""
    from . import ik_match_diag as diag
    if len(jobs) < 2:
        return bool(diag.reject('batch', 'single_chain'))
    return _dependency_audit(obj, jobs, separate=True) is not None


def _is_self_contained(obj, jobs):
    """True when the rig is one closed dependency island.

    Isolating the rig into a temporary scene, and hiding downstream meshes,
    both need this, and neither needs the limbs to be independent of each other.
    """
    return _dependency_audit(obj, jobs, separate=False) is not None


def _evaluate_match_steps(context, steps, batch):
    from . import ik_match_diag as diag
    if not batch:
        for step in steps:
            for _ in step:
                if diag.enabled():
                    start = time.perf_counter()
                    context.view_layer.update()
                    diag.add('search', time.perf_counter() - start, 1)
                else:
                    context.view_layer.update()
        return
    from .ik_native import evaluate_steps
    evaluate_steps(context, steps, batch)


@contextmanager
def _defer_match_meshes(context, obj, enabled):
    """Defer downstream geometry only after proving the rig is independent.

    hide_viewport removes mesh evaluation from the graph; disabling just the
    Armature modifier still evaluates the rest of the mesh stack. Never mute
    shared actions or user visibility animation. The caller restores the frame
    and evaluates after this scope, including when a solve raises.
    """
    from ..anim.fcurve_compat import get_all_action_fcurves
    hidden = []
    drivers = []
    try:
        for mesh in context.scene.objects if enabled else ():
            if (mesh.type != 'MESH' or mesh.library is not None
                    or (mesh.parent != obj and not any(
                        mod.type == 'ARMATURE' and mod.object == obj for mod in mesh.modifiers))):
                continue
            animation = mesh.animation_data
            visibility = []
            if animation:
                if animation.nla_tracks or (animation.action and any(
                    fc.data_path == 'hide_viewport'
                    for fc in get_all_action_fcurves(animation.action, id_type='OBJECT')
                )):
                    continue
                visibility = [fc for fc in animation.drivers if fc.data_path == 'hide_viewport']
                # Imported Smash visibility is pure armature-property input.
                # Leave custom visibility drivers entirely alone.
                safe = True
                for fc in visibility:
                    driver = fc.driver
                    if driver.type != 'SCRIPTED' or len(driver.variables) != 1:
                        safe = False
                        break
                    var = driver.variables[0]
                    target = var.targets[0]
                    if (var.type != 'SINGLE_PROP' or target.id != obj.data
                            or not target.data_path.startswith('sub_anim_properties.vis_track_entries[')
                            or not target.data_path.endswith('].value')
                            or driver.expression != '1 - ' + var.name):
                        safe = False
                        break
                if not safe:
                    continue
            hidden.append((mesh, mesh.hide_viewport))
            for fc in visibility:
                drivers.append((fc, fc.mute))
                fc.mute = True
            mesh.hide_viewport = True
        yield
    finally:
        for fc, mute in reversed(drivers):
            fc.mute = mute
        for mesh, value in reversed(hidden):
            mesh.hide_viewport = value


# Residual at or below which the solved chain is treated as matching the
# sampled FK pose. Same threshold the refinement already used to stop.
_POLE_TOLERANCE = 1e-9
# Golden-section iterations used to refine the pole angle. See the note in
# _match_chain_steps for why the search is kept at all.
#
# Was 18. Swept over six varied clips (.tests/benchmarks/ik_apply/pole_sweep.py):
# at 12 the median limb error moves by nothing measurable on any clip and the
# worst frame is identical to five decimals, while the match runs 1.18x faster.
# Below 12 small regressions start appearing -- 0.5% of the median at 10, 3.6%
# at 4 -- so 12 is where the search has genuinely converged rather than where
# the trade merely still looks acceptable.
_POLE_REFINE_STEPS = 12


def _chain_cache(obj, jobs):
    """Per-chain topology and pole angle, resolved once instead of per frame."""
    cache = {}
    for _kind, names, target, _pole in jobs:
        path = limb_path(obj, names)
        solver_root = obj.pose.bones.get(PREFIX + path[0]) if path else None
        parent = solver_root.parent if solver_root is not None else None
        cache[target] = {
            'path': path,
            # The solver chain hangs off the FK root's parent, which sits
            # outside the limb and so needs sampling as a placement reference.
            'parent': parent.name if parent is not None else None,
            'angle': None,
            'foot': foot_controls(names, obj),
            'articulation': toe_articulation(obj, names),
        }
    return cache


def _sample_names(obj, jobs, cache):
    """Bones whose world matrices the match needs, in a stable order."""
    names = []
    for _kind, _chain, target, _pole in jobs:
        entry = cache[target]
        names.extend(entry['path'])
        if entry['foot'] and entry['foot'][3] in obj.pose.bones:
            names.append(entry['foot'][3])
        if entry['articulation']:
            names.append(entry['articulation'][2])
        if entry['parent']:
            names.append(entry['parent'])
    return list(dict.fromkeys(names))



def _match_chain_steps(obj, job, matrices, frame, key, writer, entry, previous_pole, _native=None):
    """Yield at evaluation barriers; preserve each chain's original solve order.

    Seed, target and pole placement use arithmetic where possible. Independent
    chains share evaluations during the pole search without changing its order
    or convergence tolerance.
    """
    from . import ik_match_diag as diag
    kind, names, target, pole = job
    path = entry['path']
    solver = [obj.pose.bones[PREFIX + name] for name in path]
    con = solver[-2].constraints['SUB IK Solve']
    endpoints = end_constraints(solver[-1])

    # Place the solver seed. Every target matrix is already sampled, so these
    # are basis writes with nothing to evaluate between them. A bone pose_math
    # cannot model falls back to the setter, which does need a barrier -- and
    # then the solver has to be muted so it does not fight the placement.
    parent_world = matrices.get(entry['parent'])
    for index, name in enumerate(path):
        pose_bone = obj.pose.bones[PREFIX + name]
        reference = matrices[path[index - 1]] if index else parent_world
        if not pose_math.apply_world(pose_bone, matrices[name], reference):
            con.mute = True
            for endpoint in endpoints:
                endpoint.mute = True
            pose_bone.matrix = matrices[name]
            yield

    # Independent seed channels preserve animated bone length,
    # translation and axial twist without reading FK during playback.
    if key:
        for name in path:
            writer.stash_pose_bone(obj.pose.bones[PREFIX + name], frame)

    middle = bend_name(obj, names)
    root, mid, end = [matrices[n].translation for n in (path[0], middle, path[-1])]
    axis = end - root
    if axis.length < 1e-8:
        axis = matrices[names[0]].to_3x3().col[1].normalized()
    else:
        axis.normalize()
    bend = mid - root - axis * (mid - root).dot(axis)
    if bend.length < max((mid-root).length, 1.0) * 1e-5:
        bend = previous_pole.get(target, matrices[names[0]].to_3x3().col[0]).copy()
        bend -= axis * bend.dot(axis)
        if bend.length < 1e-8:
            bend = axis.orthogonal()
    bend.normalize()
    previous_pole[target] = bend.copy()

    control = obj.pose.bones[target]
    control.rotation_mode = 'QUATERNION'
    if not pose_math.apply_world(control, matrices[path[-1]], None):
        control.matrix = matrices[path[-1]]
        yield

    foot = entry.get('foot')
    if foot and all(name in obj.pose.bones for name in foot[:3]) and foot[3] in matrices:
        roll_pb = obj.pose.bones[foot[0]]
        roll_pb.matrix_basis = Matrix.Identity(4)
        toe_pb = obj.pose.bones[foot[1]]
        if not pose_math.apply_world(toe_pb, matrices[foot[3]], matrices[path[-1]]):
            toe_pb.matrix = matrices[foot[3]]
            yield

    articulation = entry.get('articulation')
    if articulation:
        bend_name_, basis_name, root_toe = articulation
        obj.pose.bones[bend_name_].matrix_basis = Matrix.Identity(4)
        # Match in the known neutral-roll frame rather than reading a stale
        # evaluated parent during per-chain matching.
        roll_world = matrices[path[-1]] @ pose_math.offset_matrix(obj.data.bones[foot[0]])
        basis_pb = obj.pose.bones[basis_name]
        if not pose_math.apply_world(basis_pb, matrices[root_toe], roll_world):
            yield
            basis_pb.matrix = matrices[root_toe]
            yield

    pole_pb = obj.pose.bones[pole]
    current = pose_math.world_from_basis(pole_pb, pole_pb.matrix_basis, None)
    if current is None:
        # Parented pole control: its world matrix has to be read, not derived.
        yield
        current = pole_pb.matrix.copy()
    placed = current.copy()
    if kind == 'ARMS' and arm_pull_value(obj, pole) > 0.0 \
            and obj.data.sub_ik_stretch_arms and obj.data.sub_ik_stretch_chain_arms:
        placed.translation = mid
    else:
        placed.translation = mid + bend * max((mid-root).length + (end-mid).length, 0.5)
    if not pose_math.apply_world(pole_pb, placed, None):
        pole_pb.matrix = placed
        yield

    con.mute = False
    for endpoint in endpoints:
        endpoint.mute = False

    # Repeated candidates do not need another scene evaluation.
    native = None
    if _native is not None:
        # Capture the exact pre-IK pose once, sharing this barrier across limbs.
        con.mute = True
        yield
        native = _native(obj, job, solver[:-1], con, frame)
        con.mute = False
    reference_columns = [tuple(matrices[name].col[i].copy() for i in range(4))
                         for name in path[:-1]]
    errors = {}
    def error(angle):
        if angle in errors:
            return errors[angle]
        # After the memo check on purpose: a repeated candidate costs no
        # evaluation and must not inflate the count.
        diag.add('candidates', 0.0, 1)
        con.pole_angle = math.atan2(math.sin(angle), math.cos(angle))
        if native is not None:
            from .ik_native import Request
            request = Request(native, con.pole_angle)
            yield request
            evaluated = request.matrices
        else:
            yield
            evaluated = [bone.matrix for bone in solver[:-1]]
        # Read each evaluated RNA matrix once; keep the original arithmetic
        # and summation order so even tie-breaking in the search stays exact.
        score = sum(sum((matrix.col[i] - reference[i]).length_squared for i in range(4))
                    for matrix, reference in
                    zip(evaluated, reference_columns))
        errors[angle] = score
        return score
    def best(candidates):
        scores = []
        for candidate in candidates:
            scores.append((candidate, (yield from error(candidate))))
        return min(scores, key=lambda pair: pair[1])[0]

    con.pole_angle = 0.0
    if native is not None:
        from .ik_native import Request
        request = Request(native, 0.0)
        yield request
        zero = request.matrices
    else:
        yield
        zero = [bone.matrix for bone in solver[:-1]]
    # Angle from the zero-angle solve to the desired bend plane.
    bend_index = path.index(middle)
    delta = _angle(zero[bend_index].translation-root, mid-root, axis)
    if (mid-root-axis*(mid-root).dot(axis)).length < 1e-5:
        delta = _angle(zero[0].to_3x3().col[0], matrices[names[0]].to_3x3().col[0], axis)
    seeds = [delta, -delta, entry['angle'] or 0.0]
    # One native call per chain and frame instead of one crossing per
    # candidate. Verification mode keeps the per-candidate path, because its
    # whole purpose is comparing each candidate against Blender. The mode is
    # resolved by ik_native rather than read from the environment here, so this
    # gate and get_factory's cannot disagree about what an unset variable means.
    #
    # `not verifying()` alone is also true under SUB_NATIVE_IK=0. That is safe
    # only because `native is not None` implies get_factory admitted the mode,
    # which is true but only at a distance, so the enabled-mode test is spelled
    # out here rather than left to be re-derived by the next reader.
    from . import ik_native
    found = None
    if (native is not None and os.environ.get('SUB_NATIVE_SEARCH', '1') == '1'
            and ik_native.enabled() and not ik_native.verifying()):
        found = native.search(reference_columns, seeds, _POLE_TOLERANCE, _POLE_REFINE_STEPS)
        if found is None:
            # The native collinearity guard refused this chain-frame and the
            # Python search below will do the whole thing instead. Counted per
            # chain-frame so it is directly comparable to native_solves: the
            # ratio is the fallback rate, and the fallback rate is the whole
            # difference between the accelerator helping and doing nothing.
            #
            # This is the only user-visible handle on why the default might not
            # speed a particular rig up. Everything else about a decline is
            # silent by design -- the output stays correct, it just costs what
            # it always cost. Measured 0% on 24 of the 28 corpus rows and 21.3%
            # on the worst; see docs/benchmarks/native-default-2026-09-13.md.
            diag.add('native_declined', 0.0, 1)
    if found is not None:
        angle = found[0]
    else:
        angle = yield from best(seeds)
        # Refine both bone orientations, not just the knee position. This handles
        # axial twist and near-straight chains where a position-only pole test has
        # almost no useful signal.
        #
        # This search is the bulk of what a match still costs -- about 18 of its
        # evaluations per chain per frame -- but it is kept.
        #
        # Its objective looks analytically solvable: changing the pole angle
        # should rotate the solved chain rigidly about the root-to-target axis,
        # making the residual exactly C + A*cos(t) + B*sin(t), which three samples
        # would pin down. In practice it is not. Solving it that way finds angles
        # that score *lower* on this measure yet drift the end effector further
        # from the FK pose (worst-case limb error on the benchmark rig 0.415 ->
        # 0.622, median 0.039 -> 0.049), and clamping the closed form to this same
        # bracket does not fix it. The likely cause is that Blender's IK solver
        # warm-starts from the previous evaluation, so the residual depends on the
        # path taken through angles, not just the angle -- which makes a
        # small-step local search meaningful and a three-probe fit not.
        #
        # The iteration count *was* cut, from 18 to 12, once there was multi-clip
        # evidence for it -- see _POLE_REFINE_STEPS. The rest of the speedups in
        # this module come from not evaluating the *placement*, which is exact
        # arithmetic.
        if (yield from error(angle)) > _POLE_TOLERANCE:
            lo, hi = angle - .2, angle + .2
            ratio = (math.sqrt(5.0)-1.0)*.5
            a, b = hi-ratio*(hi-lo), lo+ratio*(hi-lo)
            fa = yield from error(a)
            fb = yield from error(b)
            for _ in range(_POLE_REFINE_STEPS):
                if fa < fb:
                    hi, b, fb = b, a, fa
                    a = hi-ratio*(hi-lo)
                    fa = yield from error(a)
                else:
                    lo, a, fa = a, b, fb
                    b = lo+ratio*(hi-lo)
                    fb = yield from error(b)
            angle = yield from best((angle, a, b))
    if native is not None:
        native.close()
    entry['angle'] = angle

    con.pole_angle = math.atan2(math.sin(angle), math.cos(angle))
    yield
    # Keep the sampled match residual in an independent child of each solved
    # bone. Pole IK cannot exactly reproduce arbitrary FK twist/offset chains.
    # These keys retain that detail without reading the original FK at playback.
    for name in path:
        correction = obj.pose.bones.get(CORRECTION_PREFIX + name)
        if correction is not None:
            solved = obj.pose.bones[PREFIX + name].matrix.copy()
            correction.matrix_basis = solved.inverted_safe() @ matrices[name]
            if key:
                writer.stash_pose_bone(correction, frame)
    if key:
        writer.stash_pose_bone(control, frame)
        writer.stash_pose_bone(pole_pb, frame)
        if foot and all(name in obj.pose.bones for name in foot[:2]):
            writer.stash_pose_bone(obj.pose.bones[foot[0]], frame)
            writer.stash_pose_bone(obj.pose.bones[foot[1]], frame)
        if articulation:
            for name in articulation[:2]:
                writer.stash_pose_bone(obj.pose.bones[name], frame)
        writer.stash_channel(con.path_from_id() + '.pole_angle', 0, frame,
                             con.pole_angle, solver[-2].name)


def match(context, obj, limbs='BOTH', entire=True, key=True, clean=False, _batch=False,
          _fast=True, _targets=None):
    from . import create_animation_rig as rig, anim_layers_compat
    from ..anim.fcurve_compat import get_all_action_fcurves
    from ..anim import fcurve_bulk
    ensure(obj, context, limbs)
    from . import ik_match_diag as diag
    diag.reset()
    jobs = [job for job in chains(obj, limbs) if _targets is None or job[2] in _targets]
    if not jobs:
        raise RuntimeError('No complete IK chains for the requested limbs')
    scene = context.scene
    original = scene.frame_current
    frames = range(scene.frame_start, scene.frame_end + 1) if entire else [original]
    states = [(con, con.mute) for _, con, _ in outputs(obj, limbs)]
    states.extend((con, con.mute) for _, con, _ in toe_outputs(obj, limbs))
    paused = rig._IK_FK_MUTE_SYNC_PAUSED
    rig.pause_ik_fk_mute_sync(True)
    cache = _chain_cache(obj, jobs)
    sampled = _sample_names(obj, jobs, cache)
    samples = {}
    previous_pole = {}
    writer = fcurve_bulk.PoseKeyWriter(obj) if key else None
    native_factory = None
    try:
        from . import ik_match_fast
        with rig.defer_pose_tool_updates(), rig._disable_autokey(context), anim_layers_compat.bind_driving_action_for_bake(obj, context), ik_match_fast.suspend_viewport_handlers():
            for con, _ in states:
                con.mute = True
            self_contained = _is_self_contained(obj, jobs)
            batch = _batch and self_contained and _can_batch_match(obj, jobs)
            if batch:
                from . import ik_native
                native_factory = ik_native.get_factory()
            # Capture the entire source before writing any destination channels.
            with _defer_match_meshes(context, obj, self_contained and len(frames) > 1):
                # Isolation and direct sampling need the rig to be one closed
                # dependency island. They do not need two limbs to be
                # independent of each other -- that is only what scheduling
                # them into a shared graph update requires.
                fast = (_fast and self_contained and key and entire and len(frames) >= 16
                        and bpy.app.version[:2] in {(4, 5), (5, 2)})
                with diag.stage('sample'):
                    if fast:
                        from . import ik_match_fast
                        samples = ik_match_fast.sample_fk(obj, frames, sampled,
                            get_all_action_fcurves(obj.animation_data.action, id_type='OBJECT')
                            if obj.animation_data and obj.animation_data.action else ())
                    if not samples:
                        samples = {}
                        for frame in frames:
                            scene.frame_set(frame)
                            context.view_layer.update()
                            samples[frame] = {name: obj.pose.bones[name].matrix.copy() for name in sampled}
                solve_context = (ik_match_fast.isolated(context, obj, jobs, sys.modules[__name__])
                                 if fast and ik_match_fast.can_isolate(obj, jobs, sys.modules[__name__])
                                 else nullcontext((context, obj, scene)))
                with solve_context as (work_context, work_obj, work_scene):
                    for frame, matrices in samples.items():
                        work_scene.frame_set(frame)
                        with diag.stage('place'):
                            steps = [
                                _match_chain_steps(work_obj, job, matrices, frame, key, writer,
                                                   cache[job[2]], previous_pole, native_factory)
                                for job in jobs
                            ]
                        _evaluate_match_steps(work_context, steps, batch)
            with diag.stage('write'):
                if writer is not None:
                    writer.flush()
                if key and obj.animation_data and obj.animation_data.action:
                    owned = {prefix+n for _, _, target, _ in jobs for n in cache[target]['path']
                             for prefix in (PREFIX, CORRECTION_PREFIX)} | {n for _, _, target, pole in jobs for n in (target, pole)}
                    owned.update(name for entry in cache.values() if entry['foot'] for name in entry['foot'][:3])
                    owned.update(name for entry in cache.values() if entry['articulation'] for name in entry['articulation'][:2])
                    paths = tuple(obj.pose.bones[n].path_from_id() + '.' for n in owned if n in obj.pose.bones)
                    for fc in get_all_action_fcurves(obj.animation_data.action, id_type='OBJECT'):
                        if fc.data_path.startswith(paths):
                            fcurve_bulk.set_interpolation(fc, 'LINEAR')
            if entire and key and clean:
                clean_animation(obj, limbs)
            if entire and key:
                from .anim_rig_extras import mark_ik_matched
                mark_ik_matched(obj, limbs)
    finally:
        if native_factory is not None:
            native_factory.close()
        for con, mute in states:
            con.mute = mute
        rig.pause_ik_fk_mute_sync(paused)
        scene.frame_set(original)
        context.view_layer.update()
    return len(samples) * len(jobs)


def _arithmetic_bake_ok(obj, names):
    """True when replaying the samples arithmetically equals the evaluated bake.

    Setting pb.matrix inverts the *evaluated* parent, so the two agree only
    when each baked bone actually lands on its sampled world matrix. Bones
    outside ``names`` are not checked: the bake does not key them, so their
    sampled matrices stay valid as references. Call after the output blends
    have been muted.
    """
    return pose_math.can_replay([obj.pose.bones[name] for name in names])


def _bake_reference_names(obj, names):
    """Bones to sample: the baked ones, plus unbaked parents used as references."""
    extra = pose_math.reference_names([obj.pose.bones[name] for name in names])
    return list(dict.fromkeys(names + extra))


def bake(context, obj, names, start, end, clear_constraints=True):
    """Sample first, then write local FK keys derived from the sampled matrices.

    The sample pass has to evaluate the constrained IK pose once per frame.
    The write pass does not: every bone's target world matrix is already known,
    so the basis is arithmetic (see pose_math) and the keys go out in one bulk
    pass per channel instead of a keyframe_insert per bone per frame. Rigs that
    fail _arithmetic_bake_ok fall back to the original evaluate-per-bone loop.
    """
    from . import create_animation_rig as rig, anim_layers_compat
    from . import ik_floor_contact
    from ..anim.fcurve_bulk import PoseKeyWriter
    names = [n for n in names if n in obj.pose.bones
             and not n.startswith((PREFIX, PULL_PREFIX))]
    root = obj.pose.bones.get('Trans')
    body = root.constraints.get(ik_floor_contact.BODY_CONSTRAINT) if root else None
    if body and any(kind == 'LEGS' and any(n in names for n in group)
                    for kind, group, _, _ in chains(obj)):
        if 'Trans' not in names:
            names.append('Trans')
    else:
        body = None
    names.sort(key=lambda n: len(obj.pose.bones[n].parent_recursive))
    original = context.scene.frame_current
    paused = rig._IK_FK_MUTE_SYNC_PAUSED
    rig.pause_ik_fk_mute_sync(True)
    constraints = [(pb, con, con.mute) for pb, con, _ in outputs(obj) if pb.name in names]
    constraints.extend((pb, con, con.mute) for pb, con, _ in toe_outputs(obj) if pb.name in names)
    if body:
        constraints.append((root, body, body.mute))
    samples = {}
    previous = {}
    sampled = _bake_reference_names(obj, names)
    try:
        with rig._disable_autokey(context), anim_layers_compat.bind_driving_action_for_bake(obj, context):
            for frame in range(int(start), int(end) + 1):
                context.scene.frame_set(frame)
                context.view_layer.update()
                samples[frame] = {n: obj.pose.bones[n].matrix.copy() for n in sampled}
            for _, con, _ in constraints:
                con.mute = True
            if _arithmetic_bake_ok(obj, names):
                writer = PoseKeyWriter(obj)
                for frame, matrices in samples.items():
                    for n in names:
                        pb = obj.pose.bones[n]
                        parent = pb.parent
                        basis = pose_math.basis_from_world(
                            pb, matrices[n],
                            matrices.get(parent.name) if parent is not None else None)
                        if basis is None:
                            raise RuntimeError(
                                f'{n}: no arithmetic basis despite passing the '
                                'eligibility check')
                        writer.stash_matrix_basis(pb, frame, basis)
                writer.flush()
            else:
                for frame, matrices in samples.items():
                    context.scene.frame_set(frame)
                    for n in names:
                        pb = obj.pose.bones[n]
                        pb.matrix = matrices[n]
                        context.view_layer.update()
                        _key(pb, frame, previous)
            if clear_constraints:
                for pb, con, _ in constraints:
                    con.driver_remove('influence')
                    pb.constraints.remove(con)
                if body:
                    ik_floor_contact.remove_body(obj)
            else:
                # Caller is baking away IK; leave the output disabled.
                for _, con, _ in constraints:
                    con.mute = True
    except Exception:
        for _, con, was_muted in constraints:
            con.mute = was_muted
        raise
    finally:
        rig.pause_ik_fk_mute_sync(paused)
        context.scene.frame_set(original)
        context.view_layer.update()
    return len(samples) * len(names)


def remove(context, obj, limbs='BOTH', targets=None):
    from . import create_animation_rig as rig
    from ..anim.fcurve_compat import get_all_action_fcurves, remove_fcurve
    jobs = [job for job in chains(obj, limbs) if targets is None or job[2] in targets]
    affected = {n for _,group,_,_ in jobs for n in limb_path(obj,group)}
    for _, group, _, _ in jobs:
        for name in limb_path(obj, group):
            obj.data.bones[name].hide = False
    from . import ik_floor_contact
    ik_floor_contact.remove(context, obj, controls={job[2] for job in jobs})
    names = {prefix + name
             for _, group, _, _ in jobs
             for name in limb_path(obj, group)
             for prefix in (PREFIX, PULL_PREFIX, CORRECTION_PREFIX)}
    names.update(n for _, _, target, pole in jobs for n in (target, pole))
    for kind, group, _, _ in jobs:
        controls = foot_controls(group, obj) if kind == 'LEGS' else None
        if controls:
            names.update(controls[:3])
            articulation = toe_articulation(obj, group)
            if articulation:
                names.update(articulation[:2])
            for name in connected_toe_bones(obj, group):
                toe = obj.pose.bones[name]
                con = toe.constraints.get(TOE_OUTPUT)
                if con:
                    con.driver_remove('influence')
                    toe.constraints.remove(con)
    for pb, con, _ in list(outputs(obj, limbs)):
        if pb.name not in affected:
            continue
        con.driver_remove('influence')
        pb.constraints.remove(con)
    for name in names:
        pull = obj.pose.bones.get(name) if name.startswith(PULL_PREFIX) else None
        if pull:
            for constraint in list(pull.constraints):
                constraint.driver_remove('influence')
                pull.constraints.remove(constraint)
        solver = obj.pose.bones.get(name) if name.startswith(PREFIX) else None
        if solver:
            for constraint in solver.constraints:
                constraint.driver_remove('influence')
    paths = tuple(obj.pose.bones[n].path_from_id() + '.' for n in names if n in obj.pose.bones)
    for action in rig._iter_armature_actions(obj):
        for fc in list(get_all_action_fcurves(action, id_type='OBJECT')):
            if paths and fc.data_path.startswith(paths):
                remove_fcurve(action, fc, id_type='OBJECT')
    if targets is None:
        rig._remove_ik_fk_switch_keys(obj, limbs)
    bpy.ops.object.mode_set(mode='EDIT')
    for n in names:
        if n in obj.data.edit_bones:
            obj.data.edit_bones.remove(obj.data.edit_bones[n])
    bpy.ops.object.mode_set(mode='POSE')
    rig._IK_FK_APPLYING = True
    try:
        for kind in ('ARMS', 'LEGS'):
            if limbs in (kind, 'BOTH') and (targets is None or not list(chains(obj,kind))):
                if targets is not None:
                    rig._remove_ik_fk_switch_keys(obj,kind)
                setattr(obj.data, rig._limb_switch_prop(kind), 0.0)
    finally:
        rig._IK_FK_APPLYING = False
    try:
        records = json.loads(obj.get('sub_custom_ik_chains', '[]'))
    except (ValueError, TypeError):
        records = []
    obj['sub_custom_ik_chains'] = json.dumps(
        [record for record in records if (record.get('target') not in targets if targets is not None
                                        else limbs not in (record.get('kind'), 'BOTH'))])
    return list(names)
