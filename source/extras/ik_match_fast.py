"""Restricted exact IK sampling and isolated Blender evaluation.

The numerical solver and pole-search order remain Blender's existing path.
Unsupported animation/dependencies keep the ordinary scene evaluation path.
"""
from contextlib import contextmanager
import bpy
from mathutils import Matrix
from . import pose_math


def known_handlers():
    """User handlers may depend on scene identity or write after frame_set."""
    package = __package__.rsplit('.source',1)[0] + '.source.'
    return all(getattr(fn,'__module__','').startswith(package)
               for name in ('frame_change_pre','frame_change_post',
                            'depsgraph_update_pre','depsgraph_update_post')
               for fn in getattr(bpy.app.handlers,name))


# Viewport and UI synchronisation only. None of these feeds the solve, and each
# runs once per depsgraph update, which matching performs thousands of times.
SUSPENDED_HANDLERS = (
    ('source.anim.motion_list_ui', 'motion_list_auto_sync_handler'),
    ('source.extras.stage_tools.light_nuanmb', '_stage_light_depsgraph_update'),
    ('source.retargeting', 'auto_detect_smash_armature'),
)


@contextmanager
def suspend_viewport_handlers():
    """Remove this add-on's own viewport handlers for the duration.

    Skipped entirely when a foreign handler is registered, matching the guard
    the rest of this module applies: a user handler may depend on seeing every
    update, and we do not know what it does.
    """
    if not known_handlers():
        yield
        return
    package = __package__.rsplit('.source', 1)[0] + '.'
    wanted = {package + module + '.' + name for module, name in SUSPENDED_HANDLERS}
    removed = []
    try:
        for listname in ('frame_change_pre', 'frame_change_post',
                         'depsgraph_update_pre', 'depsgraph_update_post'):
            handlers = getattr(bpy.app.handlers, listname)
            for index in range(len(handlers) - 1, -1, -1):
                function = handlers[index]
                identity = (getattr(function, '__module__', '') + '.'
                            + getattr(function, '__name__', ''))
                if identity in wanted:
                    removed.append((listname, index, function))
                    handlers.remove(function)
        yield
    finally:
        # Reinsert at the original index so handler order is preserved. The
        # removals ran high index first, so replaying them in reverse restores
        # the lower indices before the higher ones depend on them.
        for listname, index, function in reversed(removed):
            getattr(bpy.app.handlers, listname).insert(index, function)


def sample_fk(obj, frames, names, curves):
    """Return exact detached FK samples, or None for unsupported inputs.

    Use Blender's channel-to-basis conversion and stored bone_mat/head offsets.
    Reconstructing offsets from inverse rest matrices changes float rounding.
    Identity parent rest avoids that inversion in convert_local_to_pose, while
    the actual evaluated parent pose preserves Blender's composition order.
    """
    anim = obj.animation_data
    if (not anim or not anim.action or anim.action_blend_type != 'REPLACE'
            or anim.action_influence != 1.0
            or (anim.use_nla and any(not t.mute for t in anim.nla_tracks))
            or len(getattr(anim.action,'slots',())) > 1 or not known_handlers()):
        return None
    needed = set(names)
    for name in names:
        needed.update(b.name for b in obj.pose.bones[name].parent_recursive)
    originals = [obj.pose.bones[n] for n in needed]
    if any(not pose_math.supports(pb) or pb.bone.use_connect
           or any(not con.mute for con in pb.constraints) for pb in originals):
        return None
    # Even a fully muted constraint stack can pass through Blender's object
    # space conversions. With a transformed object those round-trips need not
    # reproduce a direct armature-space composition exactly. Read matrix_basis
    # too: matrix_world can still be stale immediately after editing transforms.
    identity_rows = tuple(tuple(r) for r in Matrix.Identity(4))
    if any(pb.constraints for pb in originals) and (
            tuple(tuple(r) for r in obj.matrix_basis) != identity_rows
            or tuple(tuple(r) for r in obj.matrix_world) != identity_rows):
        return None
    props = ('location','rotation_quaternion','rotation_euler','rotation_axis_angle','scale')
    paths = {pb.path_from_id()+'.'+p for pb in originals for p in props}
    prefixes = tuple(pb.path_from_id()+'.' for pb in originals)
    curves = list(curves)
    object_transforms = {'location','rotation_euler','rotation_quaternion',
                         'rotation_axis_angle','scale','delta_location',
                         'delta_rotation_euler','delta_rotation_quaternion','delta_scale'}
    if any(pb.constraints for pb in originals) and any(
            not fc.mute and fc.data_path in object_transforms for fc in curves):
        return None
    seen = set()
    for fc in curves:
        if fc.mute:
            continue
        if fc.data_path.startswith(prefixes):
            channel = (fc.data_path,fc.array_index)
            if fc.data_path not in paths or channel in seen:
                return None
            seen.add(channel)
    if any(fc.data_path.startswith(prefixes) for fc in anim.drivers):
        # Muted output-constraint influence drivers cannot move sampled FK.
        muted = {c.path_from_id()+'.influence' for pb in originals
                 for c in pb.constraints if c.mute}
        if any(fc.data_path.startswith(prefixes) and fc.data_path not in muted
               for fc in anim.drivers):
            return None
    clone = obj.copy()
    try:
        clone.animation_data_clear()
        bones = sorted((clone.pose.bones[n] for n in needed),
                       key=lambda b:len(b.parent_recursive))
        offsets, channels = {}, {}
        identity = Matrix.Identity(4)
        for pb in bones:
            offset = pb.bone.matrix.to_4x4()
            offset.translation = pb.bone.head
            if pb.parent:
                offset[1][3] += pb.parent.bone.length
            offsets[pb.name] = offset
            for p in props:
                channels[pb.path_from_id()+'.'+p] = (pb,p)
        relevant = [(fc,*channels[fc.data_path]) for fc in curves
                    if not fc.mute and fc.data_path in channels]
        result = {}
        for frame in frames:
            for fc,pb,p in relevant:
                getattr(pb,p)[fc.array_index] = fc.evaluate(frame)
            worlds = {}
            for pb in bones:
                kwargs = (dict(parent_matrix=worlds[pb.parent.name],
                               parent_matrix_local=identity) if pb.parent else {})
                worlds[pb.name] = pb.bone.convert_local_to_pose(
                    pb.matrix_basis,offsets[pb.name],**kwargs)
            result[frame] = {n:worlds[n] for n in names}
        return result
    finally:
        bpy.data.objects.remove(clone)


def can_isolate(obj, jobs, ik):
    """Called only after the existing full dependency/batch guard passes."""
    if (not known_handlers() or obj.mode not in {'OBJECT','POSE'}
            or obj.pose.ik_solver != 'LEGACY' or obj.pose.use_auto_ik):
        return False
    for _,names,target,_ in jobs:
        path = ik.limb_path(obj,names)
        solver = obj.pose.bones[ik.PREFIX+path[-2]]
        endpoint = obj.pose.bones[ik.PREFIX+path[-1]]
        if (solver.constraints['SUB IK Solve'].mute
                or any(c.mute for c in ik.end_constraints(endpoint))
                or obj.pose.bones[target].rotation_mode != 'QUATERNION'):
            return False
    return True


@contextmanager
def isolated(context, obj, jobs, ik):
    """Minimal solver dependency closure; preserve rest data and RNA settings.

    Keep ancestors, including their animation and scale inheritance. Pruning
    must leave every retained rest matrix exactly unchanged, otherwise fall back.
    The destination writer still belongs to the original object.
    """
    scene = clone = data = None
    valid = False
    try:
        scene = bpy.data.scenes.new('SUB temporary IK solve')
        clone = obj.copy()
        data = obj.data.copy()
        clone.data = data
        scene.collection.objects.link(clone)
        view = scene.view_layers[0]
        view.objects.active = clone
        clone.select_set(True,view_layer=view)
        needed = set()
        for _,names,target,pole in jobs:
            needed.update(ik.PREFIX+n for n in ik.limb_path(obj,names))
            needed.update((target,pole))
            needed.update((ik.foot_controls(names,obj) or ())[:3])
            needed.update((ik.toe_articulation(obj,names) or ())[:2])
        while True:
            old = set(needed)
            for name in old:
                pb = clone.pose.bones.get(name)
                if pb is None:
                    continue
                if pb.parent:
                    needed.add(pb.parent.name)
                for con in pb.constraints:
                    for prop,sub in (('target','subtarget'),('pole_target','pole_subtarget')):
                        if getattr(con,prop,None) in (obj,clone):
                            needed.add(getattr(con,sub,''))
            if needed == old:
                break
        for pb in clone.pose.bones:
            for con in pb.constraints:
                for prop in ('target','pole_target','space_object'):
                    if getattr(con,prop,None) == obj:
                        setattr(con,prop,clone)
        if clone.animation_data:
            removed = tuple(pb.path_from_id()+'.' for pb in clone.pose.bones if pb.name not in needed)
            for fc in list(clone.animation_data.drivers):
                if fc.data_path.startswith(removed):
                    clone.animation_data.drivers.remove(fc)
                    continue
                for var in fc.driver.variables:
                    for target in var.targets:
                        if target.id == obj.data:
                            target.id = data
                        elif target.id == obj:
                            target.id = clone
        with context.temp_override(scene=scene,view_layer=view,object=clone,active_object=clone):
            bpy.ops.object.mode_set(mode='EDIT')
            for bone in list(data.edit_bones):
                if bone.name not in needed:
                    data.edit_bones.remove(bone)
            bpy.ops.object.mode_set(mode='OBJECT')
            rows = lambda m: tuple(tuple(r) for r in m)
            valid = all(rows(b.matrix_local) == rows(obj.data.bones[b.name].matrix_local)
                        and rows(b.matrix) == rows(obj.data.bones[b.name].matrix)
                        and tuple(b.head) == tuple(obj.data.bones[b.name].head)
                        and b.length == obj.data.bones[b.name].length for b in data.bones)
            if valid:
                yield context, clone, scene
    finally:
        if clone is not None:
            bpy.data.objects.remove(clone,do_unlink=True)
        if data is not None:
            bpy.data.armatures.remove(data)
        if scene is not None:
            bpy.data.scenes.remove(scene)
    if not valid:
        yield context, obj, context.scene
