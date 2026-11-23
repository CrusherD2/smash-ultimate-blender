import bpy

from . import ik_channels as ik


class CreationIKMatch:
    """Match IK during component matching from the poses it already samples."""

    def __init__(self, obj, targets):
        self.obj = obj
        self.jobs = [job for job in ik.chains(obj) if job[2] in targets]
        self.plans = ik._plans(obj, self.jobs)
        self.sample_names = ik._plan_sample_names(self.plans)
        driven = {name for plan in self.plans for name in plan['path']}
        toes = {name for _, names, _, _ in self.jobs for name in ik.connected_toe_bones(obj, names)}
        self.states = [(con, con.mute) for pb, con, _ in ik.outputs(obj) if pb.name in driven]
        self.states += [(con, con.mute) for pb, con, _ in ik.toe_outputs(obj) if pb.name in toes]
        self.samples = {}

    def prepare(self):
        pass

    def solve(self, _context, matrices, frame, _writer):
        # The pole angle is fitted over the whole range, so keys are written in finish().
        self.samples[frame] = {name: matrices[name].copy() for name in self.sample_names}

    def finish(self):
        from ..anim import fcurve_bulk
        if self.plans and self.samples:
            writer = fcurve_bulk.PoseKeyWriter(self.obj)
            ik._write_match(self.obj, self.plans, self.samples, writer)
            writer.flush()
            ik._linear_match_curves(self.obj, self.plans)
            ik._refine_offsets(bpy.context, self.obj, self.plans, self.samples, writer=ik._KeySink())
            ik._linear_match_curves(self.obj, self.plans)
        from .anim_rig_extras import mark_ik_matched
        for kind in sorted({job[0] for job in self.jobs}):
            mark_ik_matched(self.obj, kind)

    def close(self, success):
        pass
