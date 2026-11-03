"""Mirror selected edit bones across X using Smash L/R names."""
import re

import bpy
from bpy.types import Operator
from mathutils import Vector

# Same suffix rule as animation mirroring: HaveR <-> HaveL, FingerL11 <-> FingerR11.
_LR_SUFFIX = re.compile(r'^(.*)([LR])(\d*)$')


def swap_lr_bone_name(name):
    match = _LR_SUFFIX.match(name)
    if not match:
        return name
    prefix, side, digits = match.group(1), match.group(2), match.group(3)
    return f"{prefix}{'R' if side == 'L' else 'L'}{digits}"


def mirrored_vertex_group_map(names):
    """Swap a trailing L/R side on every name, vanilla or custom.

    HaveR, SwordL, and FingerL11 all qualify. Hip and Item do not, because
    they have no side suffix.
    """
    rename = {}
    for name in names:
        swapped = swap_lr_bone_name(name)
        if swapped != name:
            rename[name] = swapped
    return rename


def bone_side(name):
    match = _LR_SUFFIX.match(name)
    return match.group(2) if match else None


def _opposite(side):
    return 'R' if side == 'L' else 'L'


def _depth(bone):
    depth = 0
    current = bone
    while current.parent is not None:
        current = current.parent
        depth += 1
    return depth


def _ancestors(bone):
    names = []
    current = bone.parent
    while current is not None:
        names.append(current.name)
        current = current.parent
    return names


def _infer_side(ancestors, rename):
    for name in ancestors:
        side = bone_side(rename.get(name, name))
        if side:
            return side
    return None


class _Snap:
    def __init__(self, bone):
        self.name = bone.name
        self.parent_name = bone.parent.name if bone.parent else None
        self.ancestors = _ancestors(bone)
        self.depth = _depth(bone)
        self.head = bone.head.copy()
        self.tail = bone.tail.copy()
        self.roll = bone.roll
        self.length = bone.length
        self.use_deform = bone.use_deform
        self.use_connect = bone.use_connect
        self.inherit_scale = bone.inherit_scale
        self.use_inherit_rotation = bone.use_inherit_rotation
        self.use_local_location = bone.use_local_location
        self.use_relative_parent = bone.use_relative_parent
        self.head_radius = bone.head_radius
        self.tail_radius = bone.tail_radius
        self.envelope_distance = bone.envelope_distance
        self.envelope_weight = bone.envelope_weight
        self.collections = [collection.name for collection in bone.collections]
        self.palette = bone.color.palette
        self.custom_colors = None
        if self.palette == 'CUSTOM':
            self.custom_colors = tuple(
                tuple(getattr(bone.color.custom, channel))
                for channel in ('normal', 'select', 'active')
            )


class _Plan:
    def __init__(self, snap, source_name, mirror_name):
        self.snap = snap
        self.original = snap.name
        self.source_name = source_name
        self.mirror_name = mirror_name
        self.parent_name = snap.parent_name
        self.depth = snap.depth
        self.mirror_parent = None


def _plans_for(snaps, existing_names):
    """Name each selected bone and the bone it mirrors onto.

    A name that already ends in L or R is swapped (HaveR -> HaveL). A name
    with no side, such as Item parented under HandR, is renamed ItemR and
    mirrored as ItemL. The side comes from the nearest ancestor that has one.
    """
    skipped = []
    rename = {}
    drafts = []
    for snap in sorted(snaps, key=lambda item: (item.depth, item.name)):
        side = bone_side(snap.name)
        if side:
            source_name = snap.name
            mirror_name = swap_lr_bone_name(snap.name)
        else:
            side = _infer_side(snap.ancestors, rename)
            if side is None:
                skipped.append((snap.name, "could not tell L or R from its parents"))
                continue
            source_name = f"{snap.name}{side}"
            mirror_name = f"{snap.name}{_opposite(side)}"
        if source_name == mirror_name:
            skipped.append((snap.name, "name has no other side"))
            continue
        rename[snap.name] = source_name
        drafts.append(_Plan(snap, source_name, mirror_name))

    freed = {plan.original for plan in drafts if plan.source_name != plan.original}
    occupied = set(existing_names) - freed
    claimed = set()
    accepted = []
    for plan in drafts:
        if plan.source_name in claimed or (
            plan.source_name != plan.original and plan.source_name in occupied
        ):
            skipped.append((plan.original, f"{plan.source_name} already exists"))
            continue
        claimed.add(plan.source_name)
        occupied.add(plan.source_name)
        accepted.append(plan)

    final_names = {plan.original: plan.source_name for plan in accepted}
    for plan in accepted:
        if plan.parent_name is None:
            continue
        parent_name = final_names.get(plan.parent_name, plan.parent_name)
        plan.mirror_parent = swap_lr_bone_name(parent_name)
    return accepted, skipped


def _mirror_point(point):
    mirrored = point.copy()
    mirrored.x *= -1.0
    return mirrored


def _apply_mirrored_transform(bone, snap):
    bone.use_connect = False
    head = _mirror_point(snap.head)
    tail = _mirror_point(snap.tail)
    if (tail - head).length < 1e-8:
        tail = head + Vector((0.0, max(snap.length, 0.001), 0.0))
    bone.head = head
    bone.tail = tail
    bone.roll = -snap.roll
    bone.use_deform = snap.use_deform
    bone.inherit_scale = snap.inherit_scale
    bone.use_inherit_rotation = snap.use_inherit_rotation
    bone.use_local_location = snap.use_local_location
    bone.use_relative_parent = snap.use_relative_parent
    bone.head_radius = snap.head_radius
    bone.tail_radius = snap.tail_radius
    bone.envelope_distance = snap.envelope_distance
    bone.envelope_weight = snap.envelope_weight
    bone.color.palette = snap.palette
    if snap.custom_colors is not None:
        for channel, value in zip(('normal', 'select', 'active'), snap.custom_colors):
            getattr(bone.color.custom, channel)[:] = value


def _assign_collections(armature, bone, names):
    for name in names:
        collection = armature.collections.get(name)
        if collection is not None:
            collection.assign(bone)


def mirror_selected_bones(armature):
    """Mirror edit bones selected on `armature`.

    Returns (mirrored, skipped, warnings). `mirrored` is a list of
    (source name after rename, mirrored name). The armature must be in
    Edit Mode. Positions are mirrored across armature X, which is the
    left/right plane of an imported Smash skeleton.
    """
    bones = armature.data.edit_bones
    selected = [bone for bone in bones if bone.select]
    snaps = [_Snap(bone) for bone in selected]
    plans, skipped = _plans_for(snaps, set(bones.keys()))
    if not plans:
        return [], skipped, []

    for plan in plans:
        if plan.source_name != plan.original:
            bones[plan.original].name = plan.source_name

    mirrored_bones = []
    for plan in plans:
        bone = bones.get(plan.mirror_name)
        if bone is None:
            bone = bones.new(plan.mirror_name)
        if bone.name != plan.mirror_name:
            bones.remove(bone)
            skipped.append((plan.original, f"could not name the mirror {plan.mirror_name}"))
            continue
        _apply_mirrored_transform(bone, plan.snap)
        _assign_collections(armature.data, bone, plan.snap.collections)
        bone.select = True
        bone.select_head = True
        bone.select_tail = True
        mirrored_bones.append((plan, bone))

    warnings = []
    for plan, bone in sorted(mirrored_bones, key=lambda item: (item[0].depth, item[0].mirror_name)):
        parent = None
        if plan.mirror_parent:
            parent = bones.get(plan.mirror_parent)
            if parent is None:
                warnings.append(
                    f"{plan.mirror_name} was not parented because {plan.mirror_parent} does not exist"
                )
        bone.parent = parent
        bone.use_connect = bool(parent is not None and plan.snap.use_connect)

    if mirrored_bones:
        bones.active = mirrored_bones[-1][1]
    mirrored = [(plan.source_name, plan.mirror_name) for plan, _bone in mirrored_bones]
    return mirrored, skipped, warnings


class SUB_OP_mirror_bone(Operator):
    bl_idname = "sub.mirror_bone"
    bl_label = "Mirror Bone"
    bl_description = (
        "Mirror the selected edit bones across X. HaveR becomes HaveL and is parented "
        "to the other side of its parent (HandR -> HandL). A bone named Item parented "
        "to HandR is renamed ItemR and mirrored as ItemL"
    )
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        if obj is None or obj.type != 'ARMATURE' or context.mode != 'EDIT_ARMATURE':
            return False
        return any(bone.select for bone in obj.data.edit_bones)

    def execute(self, context):
        armature = context.active_object
        mirrored, skipped, warnings = mirror_selected_bones(armature)
        for message in warnings:
            self.report({'WARNING'}, message)
        if skipped:
            detail = "; ".join(f"{name}: {reason}" for name, reason in skipped[:4])
            extra = "" if len(skipped) <= 4 else f" (+{len(skipped) - 4} more)"
            self.report({'WARNING'}, f"Skipped {len(skipped)}: {detail}{extra}")
        if not mirrored:
            if not skipped and not warnings:
                self.report({'WARNING'}, "Select a bone to mirror")
            return {'CANCELLED'}
        pairs = ", ".join(f"{source} → {target}" for source, target in mirrored[:6])
        extra = "" if len(mirrored) <= 6 else f" (+{len(mirrored) - 6} more)"
        self.report({'INFO'}, f"Mirrored {len(mirrored)}: {pairs}{extra}")
        return {'FINISHED'}


def register():
    bpy.utils.register_class(SUB_OP_mirror_bone)


def unregister():
    bpy.utils.unregister_class(SUB_OP_mirror_bone)
