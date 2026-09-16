"""Direct channels through Blender RNA with its stored rest offsets.

Diagnostic scope: unconstrained FK ancestry and a single full-strength action.
"""
import bpy
from mathutils import Matrix


def sample(obj,frames,names,curves):
    clone = obj.copy()
    clone.animation_data_clear()
    try:
        needed = set(names)
        for name in names:
            needed.update(pb.name for pb in obj.pose.bones[name].parent_recursive)
        bones = sorted((clone.pose.bones[n] for n in needed),key=lambda b:len(b.parent_recursive))
        offsets = {}
        channels = {}
        identity = Matrix.Identity(4)
        for pb in bones:
            offset = pb.bone.matrix.to_4x4()
            offset.translation = pb.bone.head
            if pb.parent:
                offset[1][3] += pb.parent.bone.length
            offsets[pb.name] = offset
            for p in ('location','rotation_quaternion','rotation_euler','rotation_axis_angle','scale'):
                channels[pb.path_from_id()+'.'+p] = (pb,p)
        relevant = [(fc,*channels[fc.data_path]) for fc in curves if not fc.mute and fc.data_path in channels]
        result = {}
        for frame in frames:
            for fc,pb,p in relevant:
                getattr(pb,p)[fc.array_index] = fc.evaluate(frame)
            worlds = {}
            for pb in bones:
                kwargs = dict(parent_matrix=worlds[pb.parent.name],parent_matrix_local=identity) if pb.parent else {}
                worlds[pb.name] = pb.bone.convert_local_to_pose(pb.matrix_basis,offsets[pb.name],**kwargs)
            result[frame] = {n:worlds[n] for n in names}
        return result
    finally:
        bpy.data.objects.remove(clone)
