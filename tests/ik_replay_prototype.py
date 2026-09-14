"""Capture raw channels once and avoid evaluating the action a second time."""
from contextlib import contextmanager
import ik_strategy_prototypes as base

PROPS = ('location','rotation_quaternion','rotation_euler','rotation_axis_angle','scale')


def capture(obj, names):
    return {n:tuple(tuple(getattr(obj.pose.bones[n],p)) for p in PROPS) for n in names}


def needed_names(obj, ik, jobs, sampled):
    needed = set(sampled)
    for _, names, target, pole in jobs:
        needed.update(ik.PREFIX+n for n in ik.limb_path(obj,names))
        needed.update((target,pole))
        needed.update(ik.foot_controls(names,obj) or ())
        needed.update(ik.toe_articulation(obj,names) or ())
    needed.intersection_update(obj.pose.bones.keys())
    while True:
        old = set(needed)
        for name in old:
            pb = obj.pose.bones[name]
            if pb.parent:
                needed.add(pb.parent.name)
            for con in pb.constraints:
                for prop,sub in [('target','subtarget'),('pole_target','pole_subtarget')]:
                    if getattr(con,prop,None)==obj and getattr(con,sub,'') in obj.pose.bones:
                        needed.add(getattr(con,sub))
        if old==needed:
            return sorted(needed)


class Replay:
    def __init__(self,obj,states):
        self.obj,self.states=obj,states

    def frame_set(self,frame):
        for name,values in self.states[frame].items():
            pb = self.obj.pose.bones[name]
            for prop,value in zip(PROPS,values):
                setattr(pb,prop,value)


@contextmanager
def isolated(context,obj,ik,jobs,sampled,states):
    with base.isolated(context,obj,ik,jobs,sampled) as (ctx,clone,scene):
        if clone.animation_data:
            clone.animation_data.action = None
            clone.animation_data.use_nla = False
        yield ctx,clone,Replay(clone,states)
