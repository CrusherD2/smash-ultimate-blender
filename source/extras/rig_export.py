"""Sample the evaluated animation rig without changing or dismantling its controls."""

from contextlib import contextmanager
import bpy
from . import anim_layers_compat
from ..anim.fcurve_bulk import PoseKeyWriter
from ..anim.fcurve_compat import get_all_action_fcurves, remove_fcurve
from ..blender_compat import assign_action


def export_bone_names(obj):
    from .apply_ik_animation import get_ik_bone_names
    from .ik_channels import chains, foot_controls, toe_articulation

    controls = set(get_ik_bone_names(obj.data))
    for kind, names, target, pole in chains(obj):
        controls.update((target, pole))
        foot = foot_controls(names, obj) if kind == 'LEGS' else None
        if foot:
            controls.update(foot[:2])
            articulation = toe_articulation(obj, names)
            if articulation:
                controls.add(articulation[0])
    # Include non-deforming skeleton ancestors, but not rig mechanism/control leaves.
    skeleton = {
        b.name for b in obj.data.bones if b.use_deform and not b.name.startswith('BL_')
    }
    for name in tuple(skeleton):
        skeleton.update(b.name for b in obj.data.bones[name].parent_recursive)
    skeleton.update(name for name in ('Trans', 'Hip', 'Rot') if name in obj.data.bones)
    return [
        b.name
        for b in obj.data.bones
        if b.name in skeleton
        and not b.name.startswith('BL_')
        and b.name not in controls
        and not b.get('sub_component_control')
    ]


def needs_bake(obj):
    from .create_animation_rig import armature_has_animation_rig, armature_has_ik

    return (
        armature_has_animation_rig(obj)
        or armature_has_ik(obj)
        or any(pb.constraints for pb in obj.pose.bones)
        or bool(obj.animation_data and obj.animation_data.drivers)
    )


@contextmanager
def temporary_rig_bake(
    context, obj, start, end, include_transform=True, include_material=True
):
    if not needs_bake(obj):
        yield
        return
    if end < start:
        raise ValueError('End frame must be greater than or equal to start frame')
    from . import eye_rig, create_animation_rig as rig

    original_frame = (context.scene.frame_current, context.scene.frame_subframe)
    owners = (obj, obj.data)
    original = [
        (
            o,
            o.animation_data is not None,
            o.animation_data.action if o.animation_data else None,
            o.animation_data.action_slot if o.animation_data else None,
        )
        for o in owners
    ]
    temporary = []
    bases = {pb.name: pb.matrix_basis.copy() for pb in obj.pose.bones}
    auto = context.scene.tool_settings.use_keyframe_insert_auto
    try:
        context.scene.tool_settings.use_keyframe_insert_auto = False
        with rig.defer_pose_tool_updates(), anim_layers_compat.bind_driving_action_for_bake(
            obj, context
        ):
            obj.animation_data_create()
            source = obj.animation_data.action
            action = (
                source.copy() if source else bpy.data.actions.new('Rig Export Bake')
            )
            temporary.append(action)
            writer = PoseKeyWriter(obj)
            material_writer = PoseKeyWriter(obj.data)
            names = export_bone_names(obj) if include_transform else []
            name_set = set(names)
            transform_paths = {
                obj.pose.bones[n].path_from_id() + '.' + prop
                for n in names
                for prop in (
                    'location',
                    'scale',
                    'rotation_euler',
                    'rotation_quaternion',
                    'rotation_axis_angle',
                )
            }
            # Fresh sampled curves must not retain Noise/Cycles modifiers or a
            # second rotation representation from the copied source action.
            for fc in list(get_all_action_fcurves(action, id_type='OBJECT')):
                if fc.data_path in transform_paths:
                    remove_fcurve(action, fc, id_type='OBJECT')
            eye = (
                obj.pose.bones.get(eye_rig.EYE_CTRL_BONE) if include_material else None
            )
            tracks = []
            if eye and hasattr(obj.data, 'sub_anim_properties'):
                for ti, track in enumerate(obj.data.sub_anim_properties.mat_tracks):
                    if track.name not in eye_rig.EYE_TRACKS:
                        continue
                    for pi, prop in enumerate(track.properties):
                        if prop.name == eye_rig.CV31:
                            tracks.append((ti, pi, track.name))
            # Sample everything together before writing any keys. Fingers, custom
            # components, arbitrary driver rigs and IK see the same live graph.
            for frame in range(int(start), int(end) + 1):
                context.scene.frame_set(frame)
                context.view_layer.update()
                evaluated = obj.evaluated_get(context.evaluated_depsgraph_get())
                for name in names:
                    pb = evaluated.pose.bones[name]
                    if pb.parent and pb.parent.name in name_set:
                        relative = pb.parent.matrix.inverted_safe() @ pb.matrix
                        rest = (
                            pb.parent.bone.matrix_local.inverted_safe()
                            @ pb.bone.matrix_local
                        )
                        basis = rest.inverted_safe() @ relative
                    else:
                        basis = pb.bone.matrix_local.inverted_safe() @ pb.matrix
                    writer.stash_matrix_basis(
                        obj.pose.bones[name], frame, basis, rotation_mode='QUATERNION'
                    )
                if tracks:
                    left, right, vertical, pupil = eye_rig.compute_cv31(
                        obj, eye, context.scene.sub_scene_properties
                    )
                    for ti, pi, name in tracks:
                        path = f'sub_anim_properties.mat_tracks[{ti}].properties[{pi}].custom_vector'
                        material_writer.stash_channel(
                            path, 2, frame, left if name == 'EyeL' else right, name
                        )
                        material_writer.stash_channel(path, 3, frame, vertical, name)
                        if pupil is not None:
                            for axis in (0, 1):
                                material_writer.stash_channel(
                                    path, axis, frame, pupil, name
                                )
            writer.flush(action)
            assign_action(obj.animation_data, action)
            if material_writer:
                obj.data.animation_data_create()
                source = obj.data.animation_data.action
                sap = (
                    source.copy()
                    if source
                    else bpy.data.actions.new('Rig Export Material Bake')
                )
                temporary.append(sap)
                for fc in list(get_all_action_fcurves(sap, id_type='ARMATURE')):
                    if (fc.data_path, fc.array_index) in material_writer._channels:
                        remove_fcurve(sap, fc, id_type='ARMATURE')
                material_writer.flush(sap)
                assign_action(obj.data.animation_data, sap)
            yield
    finally:
        for owner, existed, action, slot in original:
            if existed:
                assign_action(owner.animation_data, action)
                if action is not None and slot is not None:
                    owner.animation_data.action_slot = slot
            elif owner.animation_data:
                owner.animation_data_clear()
        for action in temporary:
            bpy.data.actions.remove(action)
        for name, basis in bases.items():
            obj.pose.bones[name].matrix_basis = basis
        context.scene.tool_settings.use_keyframe_insert_auto = auto
        context.scene.frame_set(original_frame[0], subframe=original_frame[1])
