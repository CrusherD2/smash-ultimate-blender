"""Collapse duplicate ``_VIS_O_OBJShape`` meshes in the View Layer.

Imported Smash meshes are parented straight to the armature, so the outliner
lists every ``baseform_Angry_VIS_O_OBJShape.00N`` as its own row. A plain empty
parented to the armature is enough to fold those duplicates under one row
(``baseform_Angry``) without taking the meshes out of the export set.

The empty stays at the armature origin with locked transforms. Mesh world
matrices are preserved, and the armature modifier is left alone.
"""

from __future__ import annotations

import re

import bpy
from bpy.types import Operator
from mathutils import Matrix


VIS_SHAPE_SUFFIX = "_VIS_O_OBJShape"
VIS_GROUP_ID = "sub_vis_shape_group"
_BLENDER_DUPLICATE_SUFFIX = re.compile(r"(?:\.\d{3})+$")


def vis_shape_group_name(name: str) -> str | None:
    """Shared outliner name for one VIS mesh, ignoring Blender's ``.001`` suffix.

    ``baseform_Angry_VIS_O_OBJShape.002`` groups as ``baseform_Angry``.
    Names that do not end in the VIS suffix are left ungrouped.
    """
    trimmed = _BLENDER_DUPLICATE_SUFFIX.sub("", name or "")
    marker = VIS_SHAPE_SUFFIX.casefold()
    folded = trimmed.casefold()
    if not folded.endswith(marker):
        return None
    group = trimmed[: len(trimmed) - len(VIS_SHAPE_SUFFIX)].rstrip("_")
    return group or None


def is_vis_shape_group(obj) -> bool:
    if obj is None or getattr(obj, "type", None) != "EMPTY":
        return False
    getter = getattr(obj, "get", None)
    if getter is None:
        return False
    return bool(getter(VIS_GROUP_ID))


def owning_armature(obj):
    """Armature that owns this object, including through one VIS group empty."""
    current = getattr(obj, "parent", None)
    seen = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if getattr(current, "type", None) == "ARMATURE":
            return current
        if not is_vis_shape_group(current):
            return None
        current = getattr(current, "parent", None)
    return None


def resolve_armature(context):
    active = getattr(context, "active_object", None)
    if active is not None and getattr(active, "type", None) == "ARMATURE":
        return active
    owner = owning_armature(active) if active is not None else None
    if owner is not None:
        return owner
    for obj in getattr(context, "selected_objects", None) or []:
        if getattr(obj, "type", None) == "ARMATURE":
            return obj
        owner = owning_armature(obj)
        if owner is not None:
            return owner
    return None


def iter_model_meshes(armature):
    """Meshes the exporters should see, including ones folded into VIS groups."""
    if armature is None:
        return
    seen = set()
    for child in armature.children:
        if getattr(child, "type", None) == "MESH":
            if child.name not in seen:
                seen.add(child.name)
                yield child
            continue
        if not is_vis_shape_group(child):
            continue
        for grandchild in child.children:
            if getattr(grandchild, "type", None) != "MESH" or grandchild.name in seen:
                continue
            seen.add(grandchild.name)
            yield grandchild


def iter_visibility_targets(armature):
    """Direct armature children, plus anything parented under a VIS group."""
    if armature is None:
        return
    for child in armature.children:
        yield child
        if is_vis_shape_group(child):
            yield from child.children_recursive


def _is_swing_mesh(obj) -> bool:
    data = getattr(obj, "data", None)
    linked = getattr(data, "sub_swing_data_linked_mesh", None)
    return bool(getattr(linked, "is_swing_mesh", False))


def _parent_keep_world(child, parent):
    world = child.matrix_world.copy()
    basis = child.matrix_basis.copy()
    parent_world = parent.matrix_world.copy()
    child.parent = parent
    child.matrix_parent_inverse = parent_world.inverted() @ world @ basis.inverted()


def _link_with_armature(empty, armature, context):
    collections = list(armature.users_collection)
    if not collections and context is not None:
        collection = getattr(context, "collection", None)
        if collection is not None:
            collections = [collection]
    for collection in collections:
        if empty.name not in collection.objects:
            collection.objects.link(empty)


def _make_group_empty(armature, group_name, context):
    for child in armature.children:
        if is_vis_shape_group(child) and child.get(VIS_GROUP_ID) == group_name:
            return child
    empty = bpy.data.objects.new(group_name, None)
    empty.empty_display_type = "PLAIN_AXES"
    empty.empty_display_size = 0.01
    empty[VIS_GROUP_ID] = group_name
    empty.lock_location = (True, True, True)
    empty.lock_rotation = (True, True, True)
    empty.lock_scale = (True, True, True)
    _link_with_armature(empty, armature, context)
    empty.parent = armature
    empty.matrix_parent_inverse = Matrix.Identity(4)
    empty.location = (0.0, 0.0, 0.0)
    empty.rotation_euler = (0.0, 0.0, 0.0)
    empty.scale = (1.0, 1.0, 1.0)
    return empty


def _update_view_layer(context):
    view_layer = getattr(context, "view_layer", None) if context is not None else None
    if view_layer is None:
        view_layer = getattr(bpy.context, "view_layer", None)
    if view_layer is not None:
        view_layer.update()


def _candidate_meshes(armature):
    meshes = []
    for child in list(armature.children):
        if getattr(child, "type", None) == "MESH":
            meshes.append(child)
            continue
        if not is_vis_shape_group(child):
            continue
        meshes.extend(
            grandchild
            for grandchild in list(child.children)
            if getattr(grandchild, "type", None) == "MESH"
        )
    return meshes


def group_vis_shapes(armature, context=None) -> dict:
    """Parent duplicate VIS meshes under ``prefix`` empties.

    A name is grouped only when at least two meshes share it, so a one-off
    shape stays a direct child of the armature. Running again is safe.
    """
    summary = {"groups": 0, "meshes": 0}
    if armature is None or getattr(armature, "type", None) != "ARMATURE":
        return summary

    buckets: dict[str, list] = {}
    loose = []
    for mesh in _candidate_meshes(armature):
        if _is_swing_mesh(mesh):
            continue
        group_name = vis_shape_group_name(mesh.name)
        if group_name is None:
            loose.append(mesh)
            continue
        buckets.setdefault(group_name, []).append(mesh)

    pending = []
    for mesh in loose:
        if is_vis_shape_group(mesh.parent):
            pending.append((mesh, armature))

    for group_name, members in buckets.items():
        if len(members) < 2:
            for mesh in members:
                if is_vis_shape_group(mesh.parent):
                    pending.append((mesh, armature))
            continue
        empty = _make_group_empty(armature, group_name, context)
        for mesh in members:
            if mesh.parent != empty:
                pending.append((mesh, empty))
        summary["groups"] += 1
        summary["meshes"] += len(members)

    _update_view_layer(context)
    for mesh, parent in pending:
        _parent_keep_world(mesh, parent)

    for child in list(armature.children):
        if is_vis_shape_group(child) and len(child.children) == 0:
            bpy.data.objects.remove(child, do_unlink=True)
    return summary


def ungroup_vis_shapes(armature, context=None) -> int:
    """Move VIS meshes back onto the armature and delete the group empties."""
    if armature is None or getattr(armature, "type", None) != "ARMATURE":
        return 0
    _update_view_layer(context)
    removed = 0
    for empty in [child for child in list(armature.children) if is_vis_shape_group(child)]:
        for child in list(empty.children):
            _parent_keep_world(child, armature)
        bpy.data.objects.remove(empty, do_unlink=True)
        removed += 1
    return removed


class SUB_OP_group_vis_shapes(Operator):
    bl_idname = "sub.group_vis_shapes"
    bl_label = "Group VIS Shapes"
    bl_description = (
        "Fold duplicate _VIS_O_OBJShape meshes under one View Layer row. "
        "baseform_Angry_VIS_O_OBJShape, .001, and .002 sit under baseform_Angry. "
        "Mesh positions and export are unchanged"
    )
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return context.mode == "OBJECT" and resolve_armature(context) is not None

    def execute(self, context):
        armature = resolve_armature(context)
        summary = group_vis_shapes(armature, context)
        if summary["groups"] == 0:
            self.report({"INFO"}, "No duplicate _VIS_O_OBJShape meshes to group")
            return {"FINISHED"}
        self.report(
            {"INFO"},
            f"Grouped {summary['meshes']} VIS shapes into {summary['groups']} outliner groups",
        )
        return {"FINISHED"}


class SUB_OP_ungroup_vis_shapes(Operator):
    bl_idname = "sub.ungroup_vis_shapes"
    bl_label = "Ungroup VIS Shapes"
    bl_description = "Remove VIS shape outliner groups and parent those meshes to the armature again"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return context.mode == "OBJECT" and resolve_armature(context) is not None

    def execute(self, context):
        armature = resolve_armature(context)
        removed = ungroup_vis_shapes(armature, context)
        if removed == 0:
            self.report({"INFO"}, "No VIS shape groups to remove")
            return {"FINISHED"}
        self.report({"INFO"}, f"Removed {removed} VIS shape group(s)")
        return {"FINISHED"}
