"""Visibility-track naming, case merging, and index-safe cleanup helpers."""

from __future__ import annotations

import re

import bpy

from .fcurve_compat import get_all_action_fcurves, remove_fcurve, style_visibility_fcurve


VISIBILITY_PATH = re.compile(
    r"^sub_anim_properties\.vis_track_entries\[(\d+)\]\.value$"
)
_BLENDER_DUPLICATE_SUFFIX = re.compile(r"(?:\.\d{3})+$")


def visibility_name_from_mesh(mesh_name: str) -> str:
    """Return the vis-track portion of an imported Smash mesh object name."""
    name = _BLENDER_DUPLICATE_SUFFIX.sub("", mesh_name or "")
    return re.split(r"Shape|_VIS_|_O_", name, maxsplit=1, flags=re.IGNORECASE)[0]


def model_visibility_names(armature_object) -> dict[str, str]:
    """Map case-folded vis names to the model's authoritative capitalization."""
    names = {}
    if armature_object is None:
        return names
    meshes = sorted(
        (child for child in armature_object.children if child.type == "MESH"),
        key=lambda child: child.name.casefold(),
    )
    for mesh in meshes:
        name = visibility_name_from_mesh(mesh.name)
        if name:
            names.setdefault(name.casefold(), name)
    return names


def canonical_visibility_name(armature_object, name: str) -> str:
    return model_visibility_names(armature_object).get(name.casefold(), name)


def merge_imported_visibility_nodes(armature_object, nodes) -> list[tuple[str, list[bool]]]:
    """Merge case-only SSBH node duplicates using logical OR per frame."""
    mesh_names = model_visibility_names(armature_object)
    grouped = {}
    order = []
    for node in nodes:
        if not node.tracks:
            continue
        key = node.name.casefold()
        if key not in grouped:
            grouped[key] = []
            order.append(key)
        grouped[key].append([bool(value) for value in node.tracks[0].values])

    merged = []
    for key in order:
        series = grouped[key]
        frame_count = max((len(values) for values in series), default=0)
        if frame_count == 0:
            continue
        values = [
            any(track[min(frame, len(track) - 1)] for track in series if track)
            for frame in range(frame_count)
        ]
        source_name = next(node.name for node in nodes if node.name.casefold() == key)
        merged.append((mesh_names.get(key, source_name), values))
    return merged


def merge_exported_visibility_values(armature_object, named_values) -> list[tuple[str, list[bool]]]:
    """Collapse case-only export tracks, preserving visibility if either is on."""
    mesh_names = model_visibility_names(armature_object)
    grouped = {}
    order = []
    for name, values in named_values:
        key = name.casefold()
        if key not in grouped:
            grouped[key] = {"name": mesh_names.get(key, name), "values": list(values)}
            order.append(key)
            continue
        existing = grouped[key]["values"]
        frame_count = max(len(existing), len(values))
        grouped[key]["values"] = [
            (existing[min(i, len(existing) - 1)] if existing else False)
            or (values[min(i, len(values) - 1)] if values else False)
            for i in range(frame_count)
        ]
    return [(grouped[key]["name"], grouped[key]["values"]) for key in order]


def merge_raw_visibility_tracks(armature_object, tracks: list[dict]) -> list[dict]:
    """Merge case-only sparse raw tracks with constant boolean evaluation."""
    mesh_names = model_visibility_names(armature_object)
    grouped = {}
    order = []
    for track in tracks:
        name = track.get("name", "")
        keys = sorted(track.get("keys", []), key=lambda key: float(key["frame"]))
        if not name or not keys:
            continue
        folded = name.casefold()
        if folded not in grouped:
            grouped[folded] = {"name": mesh_names.get(folded, name), "series": []}
            order.append(folded)
        grouped[folded]["series"].append(keys)

    result = []
    for folded in order:
        series = grouped[folded]["series"]
        frames = sorted({float(key["frame"]) for keys in series for key in keys})

        def value_at(keys, frame):
            value = bool(keys[0].get("value", False))
            for key in keys:
                if float(key["frame"]) > frame:
                    break
                value = bool(key.get("value", False))
            return value

        merged_keys = []
        for frame in frames:
            value = any(value_at(keys, frame) for keys in series)
            if not merged_keys or merged_keys[-1]["value"] != value:
                merged_keys.append(
                    {"frame": frame, "value": value, "interpolation": "CONSTANT"}
                )
        result.append({"name": grouped[folded]["name"], "keys": merged_keys})
    return result


def _sap_actions_for_armature(armature_object) -> list[bpy.types.Action]:
    actions = []
    seen = set()

    def add(action):
        if action is not None and action.as_pointer() not in seen:
            seen.add(action.as_pointer())
            actions.append(action)

    data_animation = getattr(armature_object.data, "animation_data", None)
    if data_animation is not None:
        add(data_animation.action)
        for nla_track in data_animation.nla_tracks:
            for strip in nla_track.strips:
                add(strip.action)

    prefix = f"{armature_object.name} "
    for action in bpy.data.actions:
        if action.name.startswith(prefix) and action.name.endswith(" SAP Data"):
            add(action)
    return actions


def current_sap_action(armature_object):
    bone_animation = getattr(armature_object, "animation_data", None)
    bone_action = getattr(bone_animation, "action", None) if bone_animation else None
    if bone_action is not None:
        expected = bpy.data.actions.get(
            f"{armature_object.name} {bone_action.name} SAP Data"
        )
        return expected
    data_animation = getattr(armature_object.data, "animation_data", None)
    return getattr(data_animation, "action", None) if data_animation else None


def remap_visibility_entry_order(armature_object, new_order: list[int]) -> int:
    """Reorder/subset global entries and remap every associated SAP F-Curve."""
    sap = armature_object.data.sub_anim_properties
    old_count = len(sap.vis_track_entries)
    if len(set(new_order)) != len(new_order) or any(
        index < 0 or index >= old_count for index in new_order
    ):
        raise ValueError("new_order must contain unique valid visibility entry indices")

    old_to_new = {old_index: new_index for new_index, old_index in enumerate(new_order)}
    changed_curves = 0
    for action in _sap_actions_for_armature(armature_object):
        for fcurve in list(get_all_action_fcurves(action, id_type="ARMATURE")):
            match = VISIBILITY_PATH.match(fcurve.data_path or "")
            if match is None:
                continue
            old_index = int(match.group(1))
            new_index = old_to_new.get(old_index)
            if new_index is None:
                remove_fcurve(action, fcurve, id_type="ARMATURE")
            else:
                fcurve.data_path = (
                    f"sub_anim_properties.vis_track_entries[{new_index}].value"
                )
                style_visibility_fcurve(fcurve)
                fcurve.update()
            changed_curves += 1

    current_order = list(range(old_count))
    for new_index, old_index in enumerate(new_order):
        current_index = current_order.index(old_index)
        if current_index != new_index:
            sap.vis_track_entries.move(current_index, new_index)
            moved = current_order.pop(current_index)
            current_order.insert(new_index, moved)
    while len(sap.vis_track_entries) > len(new_order):
        sap.vis_track_entries.remove(len(sap.vis_track_entries) - 1)
    return changed_curves


def _replace_fcurve_keys_with_or(primary, duplicates):
    frames = sorted(
        {
            float(keyframe.co[0])
            for fcurve in duplicates
            for keyframe in fcurve.keyframe_points
        }
    )
    merged = []
    for frame in frames:
        value = any(bool(round(fcurve.evaluate(frame))) for fcurve in duplicates)
        if not merged or merged[-1][1] != value:
            merged.append((frame, value))

    points = primary.keyframe_points
    try:
        points.clear()
    except AttributeError:
        for keyframe in reversed(list(points)):
            points.remove(keyframe)
    if merged:
        points.add(count=len(merged))
        points.foreach_set("co", [coordinate for pair in merged for coordinate in pair])
        for keyframe in points:
            keyframe.interpolation = "CONSTANT"
    style_visibility_fcurve(primary)
    primary.update()


def _update_face_picker_names(armature_object, canonical_names, retained_keys):
    picker = getattr(armature_object.data, "sub_face_picker", None)
    if picker is None:
        return
    for expression in picker.expressions:
        seen = set()
        for index in reversed(range(len(expression.tracks))):
            track = expression.tracks[index]
            key = track.name.casefold()
            if key not in retained_keys or key in seen:
                expression.tracks.remove(index)
            else:
                track.name = canonical_names[key]
                seen.add(key)
    try:
        from ..extras.face_picker import refresh_track_choices

        refresh_track_choices(armature_object)
    except Exception:
        pass


def purge_unused_visibility_tracks(armature_object, scope: str) -> dict[str, int]:
    """Purge tracks without model meshes and merge case-only duplicates safely."""
    sap = armature_object.data.sub_anim_properties
    old_names = [entry.name for entry in sap.vis_track_entries]
    if not old_names:
        return {"entries": 0, "curves": 0, "duplicates": 0, "actions": 0}

    mesh_names = model_visibility_names(armature_object)
    canonical_names = {}
    old_index_to_key = {}
    entry_values = {}
    for index, entry in enumerate(sap.vis_track_entries):
        key = entry.name.casefold()
        old_index_to_key[index] = key
        canonical_names.setdefault(key, mesh_names.get(key, entry.name))
        entry_values[key] = entry_values.get(key, False) or bool(entry.value)

    actions = _sap_actions_for_armature(armature_object)
    current_action = current_sap_action(armature_object)
    if current_action is not None and current_action not in actions:
        actions.append(current_action)
    target_actions = actions if scope == "ALL" else ([current_action] if current_action else [])
    if not target_actions:
        return {"entries": 0, "curves": 0, "duplicates": 0, "actions": 0}
    target_action_pointers = {action.as_pointer() for action in target_actions}

    removed_curves = 0
    referenced_keys = set()
    for action in actions:
        grouped = {}
        for fcurve in list(get_all_action_fcurves(action, id_type="ARMATURE")):
            match = VISIBILITY_PATH.match(fcurve.data_path or "")
            if match is None:
                continue
            old_index = int(match.group(1))
            key = old_index_to_key.get(old_index)
            remove = key is None or (
                action.as_pointer() in target_action_pointers and key not in mesh_names
            )
            if remove:
                remove_fcurve(action, fcurve, id_type="ARMATURE")
                removed_curves += 1
                continue
            grouped.setdefault(key, []).append(fcurve)
            referenced_keys.add(key)

        for key, fcurves in grouped.items():
            primary = fcurves[0]
            if len(fcurves) > 1:
                _replace_fcurve_keys_with_or(primary, fcurves)
                for duplicate in fcurves[1:]:
                    remove_fcurve(action, duplicate, id_type="ARMATURE")
                    removed_curves += 1

    retained_keys = []
    for index in range(len(old_names)):
        key = old_index_to_key[index]
        if key in referenced_keys and key not in retained_keys:
            retained_keys.append(key)
    new_indices = {key: index for index, key in enumerate(retained_keys)}

    # Change paths only after merging so case duplicates can still be evaluated.
    for action in actions:
        for fcurve in get_all_action_fcurves(action, id_type="ARMATURE"):
            match = VISIBILITY_PATH.match(fcurve.data_path or "")
            if match is None:
                continue
            key = old_index_to_key.get(int(match.group(1)))
            if key in new_indices:
                fcurve.data_path = (
                    f"sub_anim_properties.vis_track_entries[{new_indices[key]}].value"
                )
                style_visibility_fcurve(fcurve)
                fcurve.update()

    old_count = len(old_names)
    duplicate_count = old_count - len(set(old_index_to_key.values()))
    sap.vis_track_entries.clear()
    for key in retained_keys:
        entry = sap.vis_track_entries.add()
        entry.name = canonical_names[key]
        entry.value = entry_values[key]
    sap.active_vis_track_index = min(
        sap.active_vis_track_index,
        max(len(sap.vis_track_entries) - 1, 0),
    )

    _update_face_picker_names(
        armature_object,
        canonical_names,
        set(retained_keys),
    )
    return {
        "entries": old_count - len(retained_keys),
        "curves": removed_curves,
        "duplicates": duplicate_count,
        "actions": len(target_actions),
    }
