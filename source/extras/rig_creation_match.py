from . import ik_channels as ik


class CreationIKMatch:
    def __init__(self, obj, targets):
        self.obj = obj
        self.jobs = [job for job in ik.chains(obj) if job[2] in targets]
        self.cache = ik._chain_cache(obj, self.jobs)
        self.sample_names = ik._sample_names(obj, self.jobs, self.cache)
        driven = {name for entry in self.cache.values() for name in entry['path']}
        toes = {name for _, names, _, _ in self.jobs for name in ik.connected_toe_bones(obj, names)}
        self.states = [(con, con.mute) for pb, con, _ in ik.outputs(obj) if pb.name in driven]
        self.states += [(con, con.mute) for pb, con, _ in ik.toe_outputs(obj) if pb.name in toes]
        self.previous_pole = {}
        self.native_factory = None
        self.batch = False
        self.old_angles = {entry['solver']: obj.pose.bones[entry['solver']].constraints['SUB IK Solve'].pole_angle
                           for entry in self.cache.values()}
        self.old_refs = {(name, prop): obj.pose.bones[name].get(prop)
                         for _, _, target, pole in self.jobs for name in (target, pole)
                         for prop in ik.REF_PROPS}

    def prepare(self):
        self.batch = ik._can_batch_match(self.obj, self.jobs) if self.jobs else False
        native_safe = self.batch or (len(self.jobs) == 1
            and ik._dependency_audit(self.obj, self.jobs, separate=True) is not None)
        if native_safe:
            from . import ik_native
            self.native_factory = ik_native.get_factory()
        ik._ensure_ref_props(self.obj, [name for _, _, target, pole in self.jobs for name in (target, pole)])

    def solve(self, context, matrices, frame, writer):
        steps = [ik._match_chain_steps(self.obj, job, matrices, frame, True, writer,
                                      self.cache[job[2]], self.previous_pole, self.native_factory,
                                      _direct_calibration=True)
                 for job in self.jobs]
        ik._evaluate_match_steps(context, steps, self.batch)

    def finish(self):
        from ..anim import fcurve_bulk
        from ..anim.fcurve_compat import get_all_action_fcurves
        owned = {prefix + name for entry in self.cache.values() for name in entry['path']
                 for prefix in (ik.PREFIX, ik.CORRECTION_PREFIX)}
        owned.update(name for _, _, target, pole in self.jobs for name in (target, pole))
        for entry in self.cache.values():
            owned.update(entry['foot'][:3] if entry['foot'] else ())
            owned.update(entry['articulation'][:2] if entry['articulation'] else ())
        paths = tuple(self.obj.pose.bones[name].path_from_id() + '.' for name in sorted(owned)
                      if name in self.obj.pose.bones)
        refs = {self.obj.pose.bones[name].path_from_id() + '["' + prop + '"]'
                for _, _, target, pole in self.jobs for name in (target, pole) for prop in ik.REF_PROPS}
        for curve in get_all_action_fcurves(self.obj.animation_data.action, id_type='OBJECT'):
            if curve.data_path.startswith(paths) or curve.data_path in refs:
                fcurve_bulk.set_interpolation(curve, 'LINEAR')
        ik._install_detail_drivers(self.obj, self.jobs)
        from .anim_rig_extras import mark_ik_matched
        for kind in sorted({job[0] for job in self.jobs}):
            mark_ik_matched(self.obj, kind)

    def close(self, success):
        if self.native_factory is not None:
            self.native_factory.close()
        if not success:
            for name, angle in self.old_angles.items():
                self.obj.pose.bones[name].constraints['SUB IK Solve'].pole_angle = angle
            for (name, prop), value in self.old_refs.items():
                pb = self.obj.pose.bones[name]
                if value is None:
                    if prop in pb:
                        del pb[prop]
                else:
                    pb[prop] = value
