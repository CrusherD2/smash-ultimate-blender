# Frozen pre-strategy match loop for exact-output differential tests.
#
# "Frozen" means the solve loop does not track ik_channels' optimisations --
# that is the whole point of the comparison. It must still accept the same
# call signature, because the harness substitutes it for the real match() and
# the add-on's own callers run against it. create_controls passes _targets, so
# this honours _targets exactly as ik_channels.match does; it takes no _fast,
# because no caller in source/ passes one and this reference has no fast path.
def match(context, obj, limbs='BOTH', entire=True, key=True, clean=False, _batch=False,
          _targets=None):
    from . import create_animation_rig as rig, anim_layers_compat
    from ..anim.fcurve_compat import get_all_action_fcurves
    from ..anim import fcurve_bulk
    ensure(obj, context, limbs)
    jobs = [job for job in chains(obj, limbs) if _targets is None or job[2] in _targets]
    if not jobs:
        raise RuntimeError('No complete IK chains for the requested limbs')
    scene = context.scene
    original = scene.frame_current
    frames = range(scene.frame_start, scene.frame_end + 1) if entire else [original]
    states = [(con, con.mute) for _, con, _ in outputs(obj, limbs)]
    states.extend((con, con.mute) for _, con, _ in toe_outputs(obj, limbs))
    paused = rig._IK_FK_MUTE_SYNC_PAUSED
    rig.pause_ik_fk_mute_sync(True)
    cache = _chain_cache(obj, jobs)
    sampled = _sample_names(obj, jobs, cache)
    samples = {}
    previous_pole = {}
    writer = fcurve_bulk.PoseKeyWriter(obj) if key else None
    native_factory = None
    try:
        with rig.defer_pose_tool_updates(), rig._disable_autokey(context), anim_layers_compat.bind_driving_action_for_bake(obj, context):
            for con, _ in states:
                con.mute = True
            batch = _batch and _can_batch_match(obj, jobs)
            if batch:
                from . import ik_native
                native_factory = ik_native.get_factory()
            # Capture the entire source before writing any destination channels.
            with _defer_match_meshes(context, obj, batch and len(frames) > 1):
                for frame in frames:
                    scene.frame_set(frame)
                    context.view_layer.update()
                    samples[frame] = {name: obj.pose.bones[name].matrix.copy() for name in sampled}
                for frame, matrices in samples.items():
                    scene.frame_set(frame)
                    steps = [
                        _match_chain_steps(obj, job, matrices, frame, key, writer,
                                           cache[job[2]], previous_pole, native_factory)
                        for job in jobs
                    ]
                    _evaluate_match_steps(context, steps, batch)
            if writer is not None:
                writer.flush()
            if key and obj.animation_data and obj.animation_data.action:
                owned = {PREFIX+n for _, _, target, _ in jobs for n in cache[target]['path']} | {n for _, _, target, pole in jobs for n in (target, pole)}
                owned.update(name for entry in cache.values() if entry['foot'] for name in entry['foot'][:3])
                owned.update(name for entry in cache.values() if entry['articulation'] for name in entry['articulation'][:2])
                paths = tuple(obj.pose.bones[n].path_from_id() + '.' for n in owned if n in obj.pose.bones)
                for fc in get_all_action_fcurves(obj.animation_data.action, id_type='OBJECT'):
                    if fc.data_path.startswith(paths):
                        fcurve_bulk.set_interpolation(fc, 'LINEAR')
            if entire and key and clean:
                clean_animation(obj, limbs)
            if entire and key:
                from .anim_rig_extras import mark_ik_matched
                mark_ik_matched(obj, limbs)
    finally:
        if native_factory is not None:
            native_factory.close()
        for con, mute in states:
            con.mute = mute
        rig.pause_ik_fk_mute_sync(paused)
        scene.frame_set(original)
        context.view_layer.update()
    return len(samples) * len(jobs)


