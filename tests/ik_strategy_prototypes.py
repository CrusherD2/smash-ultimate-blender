"""Benchmark-only experiments. No production backend is selected here."""
from contextlib import contextmanager
import bpy
from mathutils import Matrix, Quaternion, Euler, Vector


@contextmanager
def isolated(context, obj, ik, jobs, sampled, minimal=False):
    """Keep exact rest data and dependency closure; evaluate in a private scene."""
    scene = bpy.data.scenes.new('IK benchmark isolated')
    clone = obj.copy()
    data = obj.data.copy()
    clone.data = data
    scene.collection.objects.link(clone)
    view = scene.view_layers[0]
    view.objects.active = clone
    clone.select_set(True, view_layer=view)
    try:
        needed = set() if minimal else set(sampled)
        for _, names, target, pole in jobs:
            needed.update(ik.PREFIX+n for n in ik.limb_path(obj,names))
            needed.update((target,pole))
            foot = ik.foot_controls(names,obj) or ()
            articulation = ik.toe_articulation(obj,names) or ()
            needed.update(foot[:3] if minimal else foot)
            needed.update(articulation[:2] if minimal else articulation)
        # Include parents and every same-object constraint target recursively.
        while True:
            old = set(needed)
            for name in old:
                pb = clone.pose.bones.get(name)
                if pb is None:
                    continue
                if pb.parent:
                    needed.add(pb.parent.name)
                for con in pb.constraints:
                    for prop, sub in [('target','subtarget'),('pole_target','pole_subtarget')]:
                        if getattr(con,prop,None) in (obj,clone):
                            needed.add(getattr(con,sub,''))
            if old == needed:
                break
        for pb in clone.pose.bones:
            for con in pb.constraints:
                for prop in ('target','pole_target','space_object'):
                    if getattr(con,prop,None) == obj:
                        setattr(con,prop,clone)
        if clone.animation_data:
            for fc in clone.animation_data.drivers:
                for var in fc.driver.variables:
                    for target in var.targets:
                        if target.id == obj.data:
                            target.id = data
                        elif target.id == obj:
                            target.id = clone
        with context.temp_override(scene=scene, view_layer=view, object=clone,
                                   active_object=clone):
            bpy.ops.object.mode_set(mode='EDIT')
            for bone in list(data.edit_bones):
                if bone.name not in needed:
                    data.edit_bones.remove(bone)
            bpy.ops.object.mode_set(mode='OBJECT')
            print('ISOLATED_BONES',len(obj.data.bones),len(data.bones),flush=True)
            yield context, clone, scene
    finally:
        bpy.data.objects.remove(clone,do_unlink=True)
        bpy.data.armatures.remove(data)
        bpy.data.scenes.remove(scene)


def direct_samples(obj, frames, names, curves):
    """Direct action evaluation, Blender inheritance API, no depsgraph per frame.

    Diagnostic only: assumes an unlayered FK action with unconstrained ancestors.
    Caller compares every sampled matrix with the normal evaluated result.
    """
    needed = set(names)
    for name in names:
        needed.update(b.name for b in obj.pose.bones[name].parent_recursive)
    bones = sorted((obj.pose.bones[n] for n in needed),key=lambda b:len(b.parent_recursive))
    props = ('location','rotation_quaternion','rotation_euler','rotation_axis_angle','scale')
    defaults = {b.name:{p:list(getattr(b,p)) for p in props} for b in bones}
    channels = {}
    for b in bones:
        for p in props:
            channels[b.path_from_id()+'.'+p] = (b.name,p)
    relevant = [(fc,channels[fc.data_path]) for fc in curves if fc.data_path in channels and not fc.mute]
    result = {}
    for frame in frames:
        values = {n:{p:list(v) for p,v in d.items()} for n,d in defaults.items()}
        for fc,(name,prop) in relevant:
            values[name][prop][fc.array_index] = fc.evaluate(frame)
        worlds = {}
        for pb in bones:
            v = values[pb.name]
            if pb.rotation_mode == 'QUATERNION':
                rot = Quaternion(v['rotation_quaternion'])
                rot.normalize()
            elif pb.rotation_mode == 'AXIS_ANGLE':
                aa = v['rotation_axis_angle']
                rot = Quaternion(Vector(aa[1:]),aa[0])
            else:
                rot = Euler(v['rotation_euler'],pb.rotation_mode)
            basis = Matrix.LocRotScale(Vector(v['location']),rot,Vector(v['scale']))
            kwargs = dict(parent_matrix=worlds[pb.parent.name],
                          parent_matrix_local=pb.parent.bone.matrix_local) if pb.parent else {}
            worlds[pb.name] = pb.bone.convert_local_to_pose(basis,pb.bone.matrix_local,**kwargs)
        result[frame] = {n:worlds[n] for n in names}
    return result
