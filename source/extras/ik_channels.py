"""Independent IK limbs that match FK 1:1 without correction bones.

Each limb has a hidden solver chain with one IK constraint, a hidden pose chain
that adds FK location keys back onto the solved rotations, and one output
constraint per FK bone. Matching keys the solver with the FK rotations and puts
the controls where FK puts them, so the solve starts already solved.
"""
import math
import json
import uuid
import re
import bpy
from mathutils import Matrix, Vector

from . import pose_math

PREFIX = 'BL_SUB_IK_'
PULL_PREFIX = 'BL_SUB_IK_PULL_'
CORRECTION_PREFIX = 'BL_SUB_IK_MATCH_'  # legacy rigs only; removed on update
POSE_PREFIX = 'BL_SUB_IK_POSE_'
OFFSET_PREFIX = 'BL_SUB_IK_OFS_'
POSE_ROTATION = 'SUB IK Pose Rotation'
POSE_SCALE = 'SUB IK Pose Scale'
FITTED_KEY = 'sub_ik_pole_fitted'
_MIN_UP = 0.35
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
PULL_BASE = 'SUB IK Pull Base'
PULL_AIM = 'SUB IK Arm Pull Aim'
FOLLOW_PROPERTY = 'sub_ik_stretch_follow_'


def _toe_roots_under(foot_bone):
    """Shallowest toe-named descendants of the foot.

    Rigs that split the toe into Toe1L / Toe2L have no bone called exactly
    ToeL, so the hierarchy is the only thing that identifies their toes.
    """
    if foot_bone is None:
        return []
    roots, pending = [], list(foot_bone.children)
    while pending:
        bone = pending.pop(0)
        if 'toe' in bone.name.lower():
            roots.append(bone)
            continue
        pending.extend(bone.children)
    return roots


def connected_toe_bones(obj, names):
    """Parented toe hierarchy; Smash joints need not use Blender Connected."""
    foot = names[-1]
    if not foot.startswith('Foot'):
        return ()
    wanted = ('Toe' + foot[4:]).lower()
    root = next((bone for bone in obj.data.bones if bone.name.lower() == wanted), None)
    roots = [root] if root is not None else _toe_roots_under(obj.data.bones.get(foot))
    if not roots:
        return ()
    result = [bone.name for bone in roots]
    pending = [child for bone in roots for child in bone.children]
    while pending:
        bone = pending.pop(0)
        if 'toe' in bone.name.lower() and bone.name not in result:
            result.append(bone.name)
        pending.extend(bone.children)
    return tuple(result)


def toe_pivot_name(obj, names):
    """Ground the deepest toe descendant, with a stable name tie-break for branches."""
    toe_names = connected_toe_bones(obj, names)
    if not toe_names:
        return None
    # Depth is measured from the foot, so sibling toe roots stay comparable.
    foot = obj.data.bones.get(names[-1])

    def depth(name):
        bone, count = obj.data.bones[name], 0
        while bone.parent is not None and bone.parent != foot:
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
    for _kind, names, target, _ in chains(obj):
        endpoint = endpoint_target(obj, names, target)
        end = obj.pose.bones.get(PREFIX + names[-1])
        if end is None:
            continue
        for con in list(end.constraints):
            if con.type == 'COPY_TRANSFORMS' and con.target == obj and con.subtarget == target:
                con.driver_remove('influence')
                end.constraints.remove(con)
        # Stretch moves the pull bones instead, measured from where the solver reached.
        old = end.constraints.get(END_LOCATION)
        if old is not None:
            old.driver_remove('influence')
            end.constraints.remove(old)
        for name, type_ in ((END_ROTATION, 'COPY_ROTATION'),
                            (END_SCALE, 'COPY_SCALE')):
            con = end.constraints.get(name)
            if con is None:
                con = end.constraints.new(type_)
                con.name = name
                con.target_space = con.owner_space = 'WORLD'
            con.target = obj
            con.subtarget = endpoint


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
    return obj.pose.bones[PREFIX + limb_path(obj, names)[-1]]


def _pole_geometry(obj, names, kind):
    part = {'LEGS': 'Leg', 'ARMS': 'Shoulder'}.get(kind)
    if part is None or not re.fullmatch(part + r'([LR])(.*)', names[0]):
        return None
    own = obj.data.bones.get(names[0])
    if own is None:
        return None
    return (Vector((0.0, -1.0 if kind == 'LEGS' else 1.0, 0.0)),
            own.parent.matrix_local.inverted_safe() if own.parent else Matrix.Identity(4))


def _pole_position(obj, names, kind, root, mid, end, bend, parent_world=None, geometry=None):
    distance = max((mid - root).length + (end - mid).length, 0.5)
    geometry = geometry if geometry is not None else _pole_geometry(obj, names, kind)
    if geometry is not None:
        forward, parent_inverse = geometry
        space = parent_world @ parent_inverse if parent_world is not None else Matrix.Identity(4)
        # Knees point forward (-Y), elbows backward (+Y), independent of rest bend.
        forward = space.to_3x3() @ forward
        if forward.length > 1e-8:
            return mid + forward.normalized() * distance
    return mid + bend * distance


def _rest_pole_head(obj, names, kind, bones):
    """Where matching will put the pole on the rest pose, so creation and match agree."""
    path = limb_path(obj, names)
    root = bones[path[0]].head
    joint = bones[bend_name(obj, names)].head
    effector = bones[path[-2]].tail
    length = max(sum((bones[b].head - bones[a].head).length for a, b in zip(path, path[1:])), 1e-6)
    axis = effector - root
    if axis.length < 1e-8:
        return _pole_position(obj, names, kind, root, joint, bones[path[-1]].head, axis.orthogonal())
    axis.normalize()
    bend = joint - root - axis * (joint - root).dot(axis)
    if bend.length < length * _STRAIGHT:
        geometry = _pole_geometry(obj, names, kind)
        side = geometry[0] if geometry is not None else bend
        bend = side - axis * side.dot(axis)
        if bend.length < 1e-8:
            bend = axis.orthogonal()
    along = axis * axis.dot(joint - root)
    return root + along + bend.normalized() * max(_chain_rest_length(obj, path), 0.5)


def create_controls(context, obj, limbs='BOTH', custom_only=False, custom_targets=None,
                    _defer_match=False):
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
        for kind, names, target, pole in jobs:
            root, mid, end = [bones[n] for n in (names[0], bend_name(obj, names), names[-1])]
            if target not in bones:
                control = bones.new(target)
                # A new bone has zero length, so assigning a matrix loses its direction.
                control.head = end.head.copy()
                control.tail = end.head + end.vector.normalized() * max(end.length * (4.0 if kind == 'ARMS' else 3.0), .1)
                control.roll = end.roll
                control.parent = None
                control.use_deform = False
            if pole not in bones:
                control = bones.new(pole)
                control.head = _rest_pole_head(obj, names, kind, bones)
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
            if _defer_match:
                ensure(obj, context, limbs)
            else:
                match(context, obj, limbs, entire=False, key=True, _batch=fresh_controls, _targets={job[2] for job in jobs})
            rig._key_use_ik(obj, context.scene.frame_current, limbs=limbs, enabled=True)
            rig._set_ik_enabled(context, obj, True, limbs=limbs)
            context.view_layer.update()
    # Animation-rig widgets stay on Create Animation Rig / Add IK. IK Tools
    # keeps octahedral bones unless this armature already has that rig.
    if rig.armature_has_animation_rig(obj):
        from .control_appearance import style_ik_controls
        style_ik_controls(context, obj)
    if jobs and fresh_controls:
        from .ik_rig_upgrade import REVISION_KEY, CURRENT_REVISION
        obj.data[REVISION_KEY] = CURRENT_REVISION
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


def _chain_rest_length(obj, path):
    total = 0.0
    for first, second in zip(path, path[1:]):
        total += (obj.data.bones[second].head_local - obj.data.bones[first].head_local).length
    return total


def pole_rotation_names(pole):
    return PREFIX + 'PoleOrbit_' + pole, PREFIX + 'PoleAim_' + pole


def _solver_layout_current(obj, names):
    path = limb_path(obj, names)
    return all(obj.data.bones[PREFIX + name].inherit_scale == 'NONE' for name in path[1:])


def ensure(obj, context, limbs='BOTH'):
    from . import create_animation_rig as rig
    jobs = list(chains(obj, limbs))
    if not jobs:
        return
    # Older rigs solved on the bone above the end; those chains are rebuilt too.
    fresh = [j for j in jobs if any(PREFIX + n not in obj.data.bones for n in limb_path(obj, j[1]))
             or solve_bone(obj, j[1]).constraints.get('SUB IK Solve') is None
             or not _solver_layout_current(obj, j[1])]
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
                # Same rest as FK, so keyed FK rotations solve to the same pose.
                dst.length = src.length
                dst.matrix = src.matrix.copy()
                dst.use_deform = False
                dst['sub_ik_generation'] = uuid.uuid4().hex
                # Matching stretches each segment on its own; inheriting would compound it.
                dst.inherit_scale = 'NONE' if src.parent and src.parent.name in path else src.inherit_scale
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
            toe_control.length = toe.length * 2.0
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
            # The owner is the end bone and is not part of the chain without use_tail.
            con.chain_count = len(path) - 1
            con.use_tail = False
            con.use_stretch = False
            con.iterations = 500
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
            dst.length = src.length
            dst.matrix = src.matrix.copy()
            dst.use_deform = False
        bpy.ops.object.mode_set(mode='POSE')
        collection = obj.data.collections.get('IK Internal') or obj.data.collections.new('IK Internal')
        collection.is_visible = False
        for name in missing_pull:
            collection.assign(obj.data.bones[PULL_PREFIX + name])
    missing_pose = [name for name in paths if POSE_PREFIX + name not in obj.data.bones]
    if missing_pose:
        bpy.ops.object.mode_set(mode='EDIT')
        bones = obj.data.edit_bones
        for name in missing_pose:
            bones.new(POSE_PREFIX + name)
        for name in missing_pose:
            src = bones[name]
            dst = bones[POSE_PREFIX + name]
            dst.length = src.length
            dst.matrix = src.matrix.copy()
            dst.use_deform = False
            dst.inherit_scale = src.inherit_scale
            dst.use_local_location = src.use_local_location
            dst.use_inherit_rotation = src.use_inherit_rotation
            parent = src.parent
            # FK's own hierarchy, so FK location keys move it exactly like the FK bone.
            dst.parent = (bones.get(POSE_PREFIX + parent.name)
                          if parent and parent.name in paths else parent)
            dst.use_connect = False
        bpy.ops.object.mode_set(mode='POSE')
        collection = obj.data.collections.get('IK Internal') or obj.data.collections.new('IK Internal')
        collection.is_visible = False
        for name in missing_pose:
            pb = obj.pose.bones[POSE_PREFIX + name]
            pb.rotation_mode = obj.pose.bones[name].rotation_mode
            collection.assign(pb.bone)
    missing_offset = [name for name in paths if OFFSET_PREFIX + name not in obj.data.bones]
    if missing_offset:
        bpy.ops.object.mode_set(mode='EDIT')
        bones = obj.data.edit_bones
        for name in missing_offset:
            src = bones[name]
            dst = bones.new(OFFSET_PREFIX + name)
            dst.length = src.length
            dst.matrix = src.matrix.copy()
            dst.use_deform = False
            # Same rest as its solver bone: its keyed rotation is the difference back to FK.
            dst.parent = bones[PREFIX + name]
            dst.use_connect = False
            dst.inherit_scale = 'NONE'
        bpy.ops.object.mode_set(mode='POSE')
        collection = obj.data.collections.get('IK Internal') or obj.data.collections.new('IK Internal')
        collection.is_visible = False
        for name in missing_offset:
            pb = obj.pose.bones[OFFSET_PREFIX + name]
            pb.rotation_mode = 'QUATERNION'
            collection.assign(pb.bone)
    obj.data[VERSION] = 4
    wire(obj)
    from . import ik_floor_contact
    ik_floor_contact.restore_pending(context, obj)
    context.view_layer.update()


def _remove_constraint(pose_bone, name):
    con = pose_bone.constraints.get(name) if pose_bone else None
    if con is not None:
        try:
            con.driver_remove('influence')
        except (TypeError, RuntimeError):
            pass
        pose_bone.constraints.remove(con)


_PULL_OWNED = (PULL_BASE, PULL_TARGET, PULL_END, 'SUB IK Progressive Scale')


def _drop_legacy_pull(pull):
    for con in list(pull.constraints):
        if con.name not in _PULL_OWNED and not con.name.startswith('SUB IK Arm Pull'):
            _remove_constraint(pull, con.name)


def _clear_pull(pull):
    for con in list(pull.constraints):
        try:
            con.driver_remove('influence')
        except (TypeError, RuntimeError):
            pass
        pull.constraints.remove(con)


def _wire_stretch(obj, kind, names, target, path, pull, index, bend_fraction, distances):
    weight = distances[index] / distances[-1] if distances[-1] > 1e-8 else index / (len(path) - 1)
    for label, subtarget, sign in (
            (PULL_TARGET, endpoint_target(obj, names, target), 1.0),
            (PULL_END, PREFIX + path[-1], -1.0)):
        # A zero weight contributes nothing at any influence.
        if abs(weight) < 1e-8:
            _remove_constraint(pull, label)
            continue
        con = pull.constraints.get(label) or pull.constraints.new('TRANSFORM')
        con.name = label
        con.target, con.subtarget = obj, subtarget
        con.target_space = con.owner_space = 'POSE'
        con.map_from = con.map_to = 'LOCATION'
        con.mix_mode = 'ADD'
        con.use_motion_extrapolate = True
        endpoint = index == len(path) - 1
        weight_term = None if endpoint else follow_weight(weight, bend_fraction)
        for axis in 'xyz':
            setattr(con, 'from_min_' + axis, 0.0)
            setattr(con, 'from_max_' + axis, 1.0)
            setattr(con, 'to_min_' + axis, 0.0)
            setattr(con, 'to_max_' + axis, sign * (1.0 if weight_term else weight))
        _stretch_chain_driver(obj, con, kind, endpoint, weight_term)
        con.mute = False


def _wire_progressive_scale(obj, kind, names, target, path, pull, index, distances):
    con = pull.constraints.get('SUB IK Progressive Scale') or pull.constraints.new('COPY_SCALE')
    con.name = 'SUB IK Progressive Scale'
    con.target, con.subtarget = obj, endpoint_target(obj, names, target)
    con.target_space = con.owner_space = 'POSE'
    weight = distances[index] / distances[-1] if distances[-1] > 1e-8 else index / (len(path) - 1)
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


def wire(obj):
    """Connect each limb: FK bone <- pose chain <- solver, plus only the features in use.

    Without Stretch or Progressive Scale a limb bone has exactly one IK
    constraint. Turning a feature on routes that limb through its hidden pull
    bones, which carry the feature constraints.
    """
    from .create_animation_rig import _ensure_constraint_influence_driver, _limb_switch_prop
    wire_end_controls(obj)
    for kind, names, target, pole in chains(obj):
        path = limb_path(obj, names)
        used = features(obj, kind, pole)
        via_pull = used['stretch'] or used['scale']
        for name in path:
            solver = obj.pose.bones.get(PREFIX + name)
            if solver:
                solver.driver_remove('ik_stretch')
                solver.ik_stretch = 0.0
        solve = solve_bone(obj, names).constraints.get('SUB IK Solve')
        if solve:
            solve.use_stretch = False
        distances = [0.0]
        for first, second in zip(path, path[1:]):
            distances.append(distances[-1] + (
                obj.data.bones[second].head_local - obj.data.bones[first].head_local).length)
        bend = bend_name(obj, names)
        bend_fraction = (distances[path.index(bend)] / distances[-1]
                         if bend in path and distances[-1] > 1e-8 else None)
        for index, name in enumerate(path):
            source = obj.pose.bones[name]
            posed = obj.pose.bones.get(POSE_PREFIX + name)
            pull = obj.pose.bones.get(PULL_PREFIX + name)
            blend = source.constraints.get(OUTPUT)
            if posed is None or blend is None:
                continue
            rotation = posed.constraints.get(POSE_ROTATION) or posed.constraints.new('COPY_ROTATION')
            rotation.name = POSE_ROTATION
            offset = OFFSET_PREFIX + name
            rotation.target = obj
            rotation.subtarget = offset if offset in obj.pose.bones else PREFIX + name
            rotation.target_space = rotation.owner_space = 'POSE'
            rotation.mix_mode = 'REPLACE'
            if index == len(path) - 1:
                # The solver end takes the hand/foot control's scale; pass it on to the real bone.
                scale = posed.constraints.get(POSE_SCALE) or posed.constraints.new('COPY_SCALE')
                scale.name = POSE_SCALE
                scale.target, scale.subtarget = obj, PREFIX + name
                scale.target_space = scale.owner_space = 'POSE'
            else:
                _remove_constraint(posed, POSE_SCALE)
            if pull is not None and via_pull:
                _drop_legacy_pull(pull)
                base = pull.constraints.get(PULL_BASE) or pull.constraints.new('COPY_TRANSFORMS')
                base.name = PULL_BASE
                base.target, base.subtarget = obj, posed.name
                base.target_space = base.owner_space = 'POSE'
                base.influence = 1.0
                pull.constraints.move(list(pull.constraints).index(base), 0)
                if used['stretch']:
                    _wire_stretch(obj, kind, names, target, path, pull, index, bend_fraction, distances)
                else:
                    _remove_constraint(pull, PULL_TARGET)
                    _remove_constraint(pull, PULL_END)
                if used['scale'] and index < len(path) - 1:
                    _wire_progressive_scale(obj, kind, names, target, path, pull, index, distances)
                else:
                    _remove_constraint(pull, 'SUB IK Progressive Scale')
                blend.subtarget = pull.name
            else:
                if pull is not None:
                    _clear_pull(pull)
                blend.subtarget = posed.name
            _ensure_constraint_influence_driver(obj, source, blend, _limb_switch_prop(kind))
            blend.mute = False
        obj.pose.bones[pole].lock_rotation = (False, False, False)
        if solve:
            solve.pole_subtarget = pole
    wire_arm_pulls(obj)
    from . import ik_floor_contact
    ik_floor_contact.rewire(obj)


def _animated(id_data, path):
    """True when ``path`` on ``id_data`` has keys or a driver in its active action."""
    from ..anim.fcurve_compat import get_all_action_fcurves
    anim = getattr(id_data, 'animation_data', None)
    if anim is None:
        return False
    if anim.drivers.find(path) is not None:
        return True
    id_type = 'ARMATURE' if isinstance(id_data, bpy.types.Armature) else 'OBJECT'
    return anim.action is not None and any(
        curve.data_path == path for curve in get_all_action_fcurves(anim.action, id_type=id_type))


def _feature(obj, prop):
    return bool(getattr(obj.data, prop, 0.0)) or _animated(obj.data, prop)


def features(obj, kind, pole):
    """Which optional limb features need constraints; everything else stays unbuilt."""
    k = kind.lower()
    stretch = _feature(obj, 'sub_ik_stretch_' + k)
    chain = stretch and _feature(obj, 'sub_ik_stretch_chain_' + k)
    scale = _feature(obj, 'sub_ik_progressive_scale_' + k)
    pull = False
    if kind == 'ARMS' and chain and pole in obj.data.bones:
        bone = obj.data.bones[pole]
        pull = (float(getattr(bone, ARM_PULL_PROPERTY, 0.0)) > 0.0
                or _animated(obj.data, bone.path_from_id() + '.' + ARM_PULL_PROPERTY))
    return {'stretch': stretch, 'chain': chain, 'scale': scale, 'pull': pull}


def _basis(pose_bone, world, parent_world):
    """``matrix_basis`` placing ``pose_bone`` at ``world`` under a known parent pose."""
    bone = pose_bone.bone
    parent = bone.parent
    if parent is None:
        return bone.convert_local_to_pose(world, bone.matrix_local, invert=True)
    return bone.convert_local_to_pose(world, bone.matrix_local, parent_matrix=parent_world,
                                      parent_matrix_local=parent.matrix_local, invert=True)


def _world(pose_bone, basis, parent_world):
    bone = pose_bone.bone
    parent = bone.parent
    if parent is None:
        return bone.convert_local_to_pose(basis, bone.matrix_local)
    return bone.convert_local_to_pose(basis, bone.matrix_local, parent_matrix=parent_world,
                                      parent_matrix_local=parent.matrix_local)


def _rest_relation(obj, ancestor, name):
    """World of ``name`` per unit ancestor world, with every basis between them at rest."""
    bones = obj.data.bones
    return bones[ancestor].matrix_local.inverted_safe() @ bones[name].matrix_local


def _plans(obj, jobs):
    plans = []
    for kind, names, target, pole in jobs:
        path = limb_path(obj, names)
        root_parent = obj.data.bones[path[0]].parent
        foot = foot_controls(names, obj) if kind == 'LEGS' else None
        if foot and not all(name in obj.pose.bones for name in foot):
            foot = None
        plans.append({
            'kind': kind, 'names': names, 'target': target, 'pole': pole, 'path': path,
            'parent': root_parent.name if root_parent else None,
            'goal': endpoint_target(obj, names, target),
            'foot': foot,
            'articulation': toe_articulation(obj, names) if foot else None,
            'bend': bend_name(obj, names),
            # Without use_tail the IK pulls the tail of the bone above the end, not the end's head.
            'reach': obj.data.bones[path[-2]].length,
            'length': max(_chain_rest_length(obj, path), 1e-6),
            'forward': _pole_geometry(obj, names, kind),
        })
    return plans


def _plan_sample_names(plans):
    names = []
    for plan in plans:
        names.extend(plan['path'])
        if plan['parent']:
            names.append(plan['parent'])
        if plan['foot']:
            names.append(plan['foot'][3])
        if plan['articulation']:
            names.append(plan['articulation'][2])
    return list(dict.fromkeys(names))


def _aimed(head, rotation, offset, toward):
    """Bone at ``head`` turned the least amount, and scaled uniformly, so the point
    ``offset`` (bone space, unscaled) lands on ``toward``. Twist about it is kept."""
    current = rotation.to_matrix() @ offset
    wanted = toward - head
    if current.length < 1e-8 or wanted.length < 1e-8:
        return Matrix.LocRotScale(head, rotation, None)
    turn = current.rotation_difference(wanted)
    scale = wanted.length / current.length
    return Matrix.LocRotScale(head, turn @ rotation, Vector((scale, scale, scale)))


def _solver_chain(obj, plan, fk):
    """FK bases for the pose chain, solver bases, and where the solver bones end up.

    Blender's IK ignores pose location inside the chain. When FK slides the
    elbow/knee or hand/foot with location keys, each solver bone is turned and
    scaled so its child starts exactly where the FK child does; without slides
    it is the FK pose itself. The solver then passes through the visible
    joints, so the controls sit on the visible hand/foot. The offset bones key
    the rotation back to FK, and the pose chain re-adds the FK location keys,
    which keeps the visible limb 1:1.
    """
    path, parent = plan['path'], plan['parent']
    bones = obj.data.bones
    bases, worlds = {}, {}
    above = fk.get(parent) if parent else None
    head = fk[path[0]].translation
    for index, name in enumerate(path):
        fk_basis = _basis(obj.pose.bones[name], fk[name], fk[path[index - 1]] if index else above)
        bases[name] = [fk_basis, None]
        rotation = fk[name].to_quaternion()
        if index < len(path) - 1:
            child = path[index + 1]
            offset = (bones[name].matrix_local.inverted_safe() @ bones[child].head_local)
            worlds[name] = _aimed(head, rotation, offset, fk[child].translation)
            head = worlds[name] @ offset
        else:
            worlds[name] = Matrix.LocRotScale(head, rotation, fk[name].to_scale())
    _nudge_straight(plan, worlds, _forward_world(plan, fk))
    for index, name in enumerate(path):
        solver = obj.pose.bones[PREFIX + name]
        basis = _basis(solver, worlds[name], worlds[path[index - 1]] if index else above)
        if index:
            basis.translation = (0.0, 0.0, 0.0)
        bases[name][1] = basis
        # Offset bones share the solver rest, so this rotation turns the solver back into FK.
        offset = worlds[name].to_quaternion().inverted() @ fk[name].to_quaternion()
        bases[name].append(Matrix.LocRotScale(None, offset, None))
    return {name: tuple(value) for name, value in bases.items()}, worlds


# Below this bend (fraction of limb length) a limb counts as straight; the solver
# seed is then bent this far toward the rig's knee-forward / elbow-back side.
_STRAIGHT = 0.01
_NUDGE = 0.001


def _nudge_straight(plan, worlds, forward):
    """Give a near-straight solver seed a tiny bend toward the pole side, in place.

    Only the hidden solver keys change. FK bones and their keys are never
    touched; the IK result on these frames differs from FK by about the nudge.
    """
    if forward is None or plan['bend'] not in plan['path'][1:-1]:
        return False
    axis, offset = _bend_offset(worlds, plan)
    if axis is None or offset.length >= plan['length'] * _STRAIGHT:
        return False
    side = forward - axis * forward.dot(axis)
    if side.length < 1e-8:
        return False
    side.normalize()
    # Keep any bend already on the pole side; only drop sideways noise or a wrong-side bend.
    bent = side * max(offset.dot(side), plan['length'] * _NUDGE)
    if (bent - offset).length < plan['length'] * 1e-6:
        return False
    path = plan['path']
    split = path.index(plan['bend'])
    root = worlds[path[0]].translation.copy()
    joint = worlds[plan['bend']].translation.copy()
    effector = _effector(worlds, plan)
    wanted = root + axis * axis.dot(joint - root) + bent
    first = (joint - root).rotation_difference(wanted - root).to_matrix().to_4x4()
    swing = Matrix.Translation(root) @ first @ Matrix.Translation(-root)
    moved_joint = swing @ joint
    moved_effector = swing @ effector
    second = (moved_effector - moved_joint).rotation_difference(effector - moved_joint).to_matrix().to_4x4()
    fold = Matrix.Translation(moved_joint) @ second @ Matrix.Translation(-moved_joint)
    for index, name in enumerate(path):
        worlds[name] = (swing if index < split else fold @ swing) @ worlds[name]
    return True


def _effector(worlds, plan):
    return worlds[plan['path'][-2]] @ Vector((0.0, plan['reach'], 0.0))


def _bend_offset(worlds, plan):
    path = plan['path']
    root, tip = worlds[path[0]].translation, _effector(worlds, plan)
    axis = tip - root
    if axis.length < 1e-8:
        return None, None
    axis.normalize()
    offset = worlds[plan['bend']].translation - root
    offset -= axis * offset.dot(axis)
    return axis, offset


def _up_axis(worlds, plan, angle, axis):
    # Blender's pole reference: the root's X axis turned by pole_angle around its Y.
    rotation = worlds[plan['path'][0]].to_3x3()
    up = rotation.col[0] * math.cos(angle) + rotation.col[2] * math.sin(angle)
    return up - axis * up.dot(axis)


def _exact_angle(worlds, plan, axis, direction):
    """Pole angle whose reference axis points along ``direction`` (perpendicular to ``axis``)."""
    rotation = worlds[plan['path'][0]].to_3x3()
    x_axis, z_axis = rotation.col[0], rotation.col[2]
    normal = axis.cross(direction)
    angle = math.atan2(-x_axis.dot(normal), z_axis.dot(normal))
    if (x_axis * math.cos(angle) + z_axis * math.sin(angle)).dot(direction) < 0.0:
        angle += math.pi
    return angle


def _bend_angle(worlds, plan):
    axis, offset = _bend_offset(worlds, plan)
    if offset is None or offset.length < 1e-6:
        return None
    return _exact_angle(worlds, plan, axis, offset.normalized())


def fit_pole_angle(chains, plan, preferred=None):
    """One pole angle per limb and action.

    Start where the knee or elbow points on average, then tilt only as far as
    needed so the pole reference never lines up with the root-to-tip axis,
    where a small pole move would spin the limb.
    """
    total = Vector((0.0, 0.0))
    for worlds in chains:
        angle = _bend_angle(worlds, plan)
        if angle is not None:
            total += Vector((math.cos(angle), math.sin(angle)))
    front = math.atan2(total.y, total.x) if total.length > 1e-8 else 0.0

    def worst(angle):
        lengths = []
        for worlds in chains:
            axis, _offset = _bend_offset(worlds, plan)
            if axis is not None:
                lengths.append(_up_axis(worlds, plan, angle, axis).length)
        return min(lengths, default=1.0)

    if preferred is not None and worst(preferred) >= _MIN_UP:
        return preferred
    best = (worst(front), front)
    for degrees in range(5, 95, 5):
        if best[0] >= _MIN_UP:
            break
        for sign in (1, -1):
            angle = front + sign * math.radians(degrees)
            best = max(best, (worst(angle), angle))
    return math.atan2(math.sin(best[1]), math.cos(best[1]))


def _forward_world(plan, fk):
    if plan['forward'] is None:
        return None
    forward, parent_inverse = plan['forward']
    parent = fk.get(plan['parent']) if plan['parent'] else None
    space = parent @ parent_inverse if parent is not None else Matrix.Identity(4)
    return space.to_3x3() @ forward


def _pole_world(obj, plan, worlds, angle, at_bend):
    path = plan['path']
    axis, offset = _bend_offset(worlds, plan)
    if axis is None:
        return None
    orientation = obj.data.bones[plan['pole']].matrix_local.to_3x3().to_4x4()
    if at_bend:
        # Arm Pull pulls toward the pole, so it must sit on the elbow to add nothing.
        return Matrix.Translation(worlds[plan['bend']].translation) @ orientation
    up = _up_axis(worlds, plan, angle, axis)
    if up.length < 1e-6:
        up = offset if offset is not None and offset.length > 1e-6 else axis.orthogonal()
    root = worlds[path[0]].translation
    along = axis * axis.dot(worlds[plan['bend']].translation - root)
    distance = max(_chain_rest_length(obj, path), 0.5)
    return Matrix.Translation(root + along + up.normalized() * distance) @ orientation


def _write_match(obj, plans, samples, writer):
    """Stash solver, pose chain and control keys that reproduce the sampled FK pose."""
    frames = sorted(samples)
    for plan in plans:
        path = plan['path']
        solved = {frame: _solver_chain(obj, plan, samples[frame]) for frame in frames}
        solve = solve_bone(obj, plan['names']).constraints['SUB IK Solve']
        at_bend = plan['kind'] == 'ARMS' and features(obj, plan['kind'], plan['pole'])['pull']
        # A one-frame match keeps the limb's angle when it works, so neighbours stay put.
        owner = solve_bone(obj, plan['names'])
        preferred = solve.pole_angle if len(frames) == 1 and owner.get(FITTED_KEY) else None
        angle = 0.0 if at_bend else fit_pole_angle([solved[f][1] for f in frames], plan, preferred)
        target = obj.pose.bones[plan['target']]
        target.rotation_mode = 'QUATERNION'
        # Reverse feet aim the solver at FootTarget, a child of FootIK.
        goal_to_target = _rest_relation(obj, plan['goal'], plan['target'])
        pole = obj.pose.bones[plan['pole']]
        for frame in frames:
            fk = samples[frame]
            bases, worlds = solved[frame]
            for name in path:
                fk_basis, solver_basis, offset_basis = bases[name]
                writer.stash_matrix_basis(obj.pose.bones[PREFIX + name], frame, solver_basis)
                writer.stash_matrix_basis(obj.pose.bones[POSE_PREFIX + name], frame, fk_basis)
                offset = obj.pose.bones.get(OFFSET_PREFIX + name)
                if offset is not None:
                    writer.stash_matrix_basis(offset, frame, offset_basis)
            goal = fk[path[-1]].copy()
            goal.translation = _effector(worlds, plan)
            placement = goal @ goal_to_target
            writer.stash_matrix_basis(target, frame, _basis(target, placement, None))
            if at_bend:
                bent = _bend_angle(worlds, plan)
                angle = bent if bent is not None else angle
            writer.stash_channel(solve.path_from_id('pole_angle'), 0, frame, angle, PREFIX + path[-1])
            pole_world = _pole_world(obj, plan, worlds, angle, at_bend)
            if pole_world is not None:
                writer.stash_matrix_basis(pole, frame, _basis(pole, pole_world, None))
            foot = plan['foot']
            if not foot:
                continue
            roll, toe, output, fk_toe = foot
            # The goal hangs off the roll at rest; a stray pose there would move the solve.
            writer.stash_matrix_basis(obj.pose.bones[roll], frame, Matrix.Identity(4))
            writer.stash_matrix_basis(obj.pose.bones[output], frame, Matrix.Identity(4))
            toe_pb = obj.pose.bones[toe]
            writer.stash_matrix_basis(toe_pb, frame, _basis(
                toe_pb, fk[fk_toe], placement @ _rest_relation(obj, plan['target'], toe_pb.parent.name)))
            articulation = plan['articulation']
            if articulation:
                bend, basis_name, root_toe = articulation
                writer.stash_matrix_basis(obj.pose.bones[bend], frame, Matrix.Identity(4))
                basis_pb = obj.pose.bones[basis_name]
                writer.stash_matrix_basis(basis_pb, frame, _basis(
                    basis_pb, fk[root_toe],
                    placement @ _rest_relation(obj, plan['target'], basis_pb.parent.name)))
        solve.pole_angle = angle
        owner[FITTED_KEY] = True


def _refine_offsets(context, obj, plans, samples, writer=None):
    """Re-key offset bones from the evaluated solve.

    Blender's IK can land a hair away from its seed (up to about 0.05 degrees
    on aimed or stretched segments); reading where it actually landed keeps
    the visible limb 1:1.
    """
    scene = context.scene
    sink = writer or _PoseSink()
    for frame in sorted(samples):
        if writer is not None:
            scene.frame_set(frame)
        context.view_layer.update()
        for plan in plans:
            fk = samples[frame]
            for name in plan['path']:
                offset = obj.pose.bones.get(OFFSET_PREFIX + name)
                if offset is None:
                    continue
                solved = obj.pose.bones[PREFIX + name].matrix.to_quaternion()
                basis = Matrix.LocRotScale(None, solved.inverted() @ fk[name].to_quaternion(), None)
                sink.stash_matrix_basis(offset, frame, basis)


def _owned_match_bones(plans):
    owned = set()
    for plan in plans:
        owned.update(prefix + name for name in plan['path'] for prefix in (PREFIX, POSE_PREFIX, OFFSET_PREFIX))
        owned.update((plan['target'], plan['pole']))
        if plan['foot']:
            owned.update(plan['foot'][:3])
        if plan['articulation']:
            owned.update(plan['articulation'][:2])
    return owned


def _linear_match_curves(obj, plans):
    from ..anim import fcurve_bulk
    from ..anim.fcurve_compat import get_all_action_fcurves
    action = obj.animation_data.action if obj.animation_data else None
    if action is None:
        return
    paths = tuple(obj.pose.bones[name].path_from_id() + '.'
                  for name in sorted(_owned_match_bones(plans)) if name in obj.pose.bones)
    angles = {solve_bone(obj, plan['names']).constraints['SUB IK Solve'].path_from_id('pole_angle')
              for plan in plans}
    for curve in get_all_action_fcurves(action, id_type='OBJECT'):
        if curve.data_path.startswith(paths) or curve.data_path in angles:
            fcurve_bulk.set_interpolation(curve, 'LINEAR')


class _KeySink:
    """Keys refined offset rotations directly, replacing the first pass's keys."""

    @staticmethod
    def stash_matrix_basis(pose_bone, frame, basis):
        pose_bone.matrix_basis = basis
        pose_bone.keyframe_insert('rotation_quaternion', frame=frame, group=pose_bone.name)


class _PoseSink:
    """Writer stand-in for an unkeyed single-frame match: pose instead of key."""

    @staticmethod
    def stash_matrix_basis(pose_bone, _frame, basis):
        pose_bone.matrix_basis = basis

    @staticmethod
    def stash_channel(*_args):
        pass


def _num(value):
    return repr(round(value, 6))


def follow_position(bend_fraction):
    """Where the bend sits along the stretch, as a driver term of ``follow``.

    0.5 keeps the rest-length proportion; 0 holds the bend at the root, 1 at the end.
    """
    return (f'(min(2*follow,1)*{_num(bend_fraction)}'
            f'+max(2*follow-1,0)*{_num(1.0 - bend_fraction)})')


def follow_weight(weight, bend_fraction):
    """Stretch share of one chain bone, remapped so the bend lands at ``follow_position``."""
    if bend_fraction is None or not 1e-6 < bend_fraction < 1.0 - 1e-6 or weight < 1e-8:
        return None
    position = follow_position(bend_fraction)
    if weight <= bend_fraction + 1e-9:
        return f'{_num(weight / bend_fraction)}*{position}'
    return f'(1-{_num((1.0 - weight) / (1.0 - bend_fraction))}*(1-{position}))'


def _stretch_chain_driver(obj, constraint, kind, endpoint, weight_term=None):
    driver = constraint.driver_add('influence').driver
    driver.type = 'SCRIPTED'
    for variable in list(driver.variables):
        driver.variables.remove(variable)
    props = [('stretch', 'sub_ik_stretch_' + kind.lower())]
    chain_prop = 'sub_ik_stretch_chain_' + kind.lower()
    if hasattr(obj.data, chain_prop):
        props.append(('chain', chain_prop))
    follow_prop = FOLLOW_PROPERTY + kind.lower()
    if weight_term and len(props) == 2 and hasattr(obj.data, follow_prop):
        props.append(('follow', follow_prop))
    for variable_name, prop in props:
        variable = driver.variables.new()
        variable.name, variable.type = variable_name, 'SINGLE_PROP'
        variable.targets[0].id_type = 'ARMATURE'
        variable.targets[0].id = obj.data
        variable.targets[0].data_path = prop
    if endpoint:
        driver.expression = 'stretch'
    elif len(props) == 3:
        driver.expression = 'stretch * chain * ' + weight_term
    else:
        driver.expression = 'stretch * chain' if len(props) == 2 else '0'


def _arm_pull_driver(obj, constraint, pole, position=None):
    driver = constraint.driver_add('influence').driver
    driver.type = 'SCRIPTED'
    for variable in list(driver.variables):
        driver.variables.remove(variable)
    inputs = [('pull', obj.data.bones[pole].path_from_id() + '.' + ARM_PULL_PROPERTY),
              ('stretch', 'sub_ik_stretch_arms'),
              ('chain', 'sub_ik_stretch_chain_arms')]
    if position is not None:
        inputs.append(('follow', FOLLOW_PROPERTY + 'arms'))
    for variable_name, data_path in inputs:
        variable = driver.variables.new()
        variable.name, variable.type = variable_name, 'SINGLE_PROP'
        variable.targets[0].id_type = 'ARMATURE'
        variable.targets[0].id = obj.data
        variable.targets[0].data_path = data_path
    driver.expression = 'pull * stretch * chain' + (' * ' + position if position else '')


def _wire_pull_aims(obj, path, bend_index, pole):
    """Keep each pulled bone before the bend pointing at the next one, so its tail follows."""
    for index, name in enumerate(path[:-1]):
        pull = obj.pose.bones.get(PULL_PREFIX + name)
        if pull is None:
            continue
        con = pull.constraints.get(PULL_AIM)
        if index >= bend_index or PULL_PREFIX + path[index + 1] not in obj.pose.bones:
            if con is not None:
                con.driver_remove('influence')
                pull.constraints.remove(con)
            continue
        con = con or pull.constraints.new('DAMPED_TRACK')
        con.name = PULL_AIM
        con.target, con.subtarget = obj, PULL_PREFIX + path[index + 1]
        con.head_tail = 0.0
        con.track_axis = 'TRACK_Y'
        pull.constraints.move(list(pull.constraints).index(con), len(pull.constraints) - 1)
        # Scales with the pull, so a zero pull leaves the matched pose untouched.
        _arm_pull_driver(obj, con, pole)
        con.mute = False


def wire_arm_pulls(obj):
    """Distribute each arm pole's independently controlled positional pull."""
    for _kind, names, target, pole in chains(obj, 'ARMS'):
        path = limb_path(obj, names)
        middle = bend_name(obj, names)
        if middle not in path or pole not in obj.pose.bones:
            continue
        if not features(obj, 'ARMS', pole)['pull']:
            for name in path:
                pull = obj.pose.bones.get(PULL_PREFIX + name)
                for con in list(pull.constraints) if pull else ():
                    if con.name.startswith('SUB IK Arm Pull'):
                        _remove_constraint(pull, con.name)
            continue
        bend_index = path.index(middle)
        distances = [0.0]
        for first, second in zip(path, path[1:]):
            distances.append(distances[-1] + (
                obj.data.bones[second].head_local - obj.data.bones[first].head_local).length)
        total, bend_distance = distances[-1], distances[bend_index]
        bend_fraction = bend_distance / total if total > 1e-8 else bend_index / (len(path) - 1)
        position = (follow_position(bend_fraction)
                    if hasattr(obj.data, FOLLOW_PROPERTY + 'arms') and 1e-6 < bend_fraction < 1 - 1e-6
                    else None)
        _wire_pull_aims(obj, path, bend_index, pole)
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
            # The stretch moved the bend by its follow share of (Hand - End); undo exactly that.
            share = 1.0 if position else bend_fraction
            terms = (
                ('Pole', pole, weight, None),
                ('Bend', PREFIX + middle, -weight, None),
                ('Hand', endpoint_target(obj, names, target), -weight * share, position),
                ('End', PREFIX + path[-1], weight * share, position),
            )
            for suffix, subtarget, factor, scale in terms:
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
                _arm_pull_driver(obj, con, pole, scale)
                con.mute = False


def upgrade_pull_controls(context, obj):
    """Add positional outputs to saved rigs without rematching their keys."""
    jobs = list(chains(obj))
    if not any(prefix + name not in obj.data.bones
               for _, names, _, _ in jobs for name in limb_path(obj, names)
               for prefix in (PULL_PREFIX, POSE_PREFIX, OFFSET_PREFIX)):
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
        names.update(prefix + n for n in limb_path(obj, group) for prefix in (PREFIX, POSE_PREFIX, OFFSET_PREFIX))
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


    # The regular audit still checks EVERY constraint/driver and rejects
    # cross-island readers, external targets and any upstream feedback.


def match(context, obj, limbs='BOTH', entire=True, key=True, clean=False, _batch=False,
          _fast=True, _targets=None):
    """Match IK to FK 1:1: FK rotations on the solver, controls where FK puts them."""
    from . import create_animation_rig as rig, anim_layers_compat
    from ..anim import fcurve_bulk
    ensure(obj, context, limbs)
    jobs = [job for job in chains(obj, limbs) if _targets is None or job[2] in _targets]
    if not jobs:
        raise RuntimeError('No complete IK chains for the requested limbs')
    plans = _plans(obj, jobs)
    scene = context.scene
    original = scene.frame_current
    frames = range(scene.frame_start, scene.frame_end + 1) if entire else [original]
    states = [(con, con.mute) for _, con, _ in outputs(obj, limbs)]
    states.extend((con, con.mute) for _, con, _ in toe_outputs(obj, limbs))
    paused = rig._IK_FK_MUTE_SYNC_PAUSED
    rig.pause_ik_fk_mute_sync(True)
    names = _plan_sample_names(plans)
    samples = {}
    try:
        with rig.defer_pose_tool_updates(), rig._disable_autokey(context), \
                anim_layers_compat.bind_driving_action_for_bake(obj, context):
            for con, _ in states:
                con.mute = True
            for frame in frames:
                scene.frame_set(frame)
                context.view_layer.update()
                samples[frame] = {name: obj.pose.bones[name].matrix.copy() for name in names}
            if key:
                writer = fcurve_bulk.PoseKeyWriter(obj)
                _write_match(obj, plans, samples, writer)
                writer.flush()
                _linear_match_curves(obj, plans)
                _refine_offsets(context, obj, plans, samples, writer=_KeySink())
                _linear_match_curves(obj, plans)
            else:
                _write_match(obj, plans, {original: samples[original]}, _PoseSink())
                _refine_offsets(context, obj, plans, {original: samples[original]})
            if entire and key and clean:
                clean_animation(obj, limbs)
            if entire and key:
                from .anim_rig_extras import mark_ik_matched
                mark_ik_matched(obj, limbs)
    finally:
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
    from ..blender_compat import set_pose_bone_hidden
    rig._migrate_ik_pose_visibility(obj)
    for kind, group, _, _ in jobs:
        toes = connected_toe_bones(obj, group) if kind == 'LEGS' else ()
        for name in (*limb_path(obj, group), *toes):
            set_pose_bone_hidden(obj.pose.bones.get(name), bool(obj.data.bones[name].get('sub_component_hidden')))
    from . import ik_floor_contact
    ik_floor_contact.remove(context, obj, controls={job[2] for job in jobs})
    names = {prefix + name
             for _, group, _, _ in jobs
             for name in limb_path(obj, group)
             for prefix in (PREFIX, PULL_PREFIX, POSE_PREFIX, OFFSET_PREFIX, CORRECTION_PREFIX)}
    names.update(n for _, _, target, pole in jobs for n in (target, pole))
    names.update(n for _, _, _, pole in jobs for n in pole_rotation_names(pole))
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
