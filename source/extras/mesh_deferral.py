"""Skip downstream mesh evaluation while an armature is posed repeatedly.

The IK match and component matching both want the same thing: the rig's pose
recomputed thousands of times without dragging every bound mesh through its
modifier stack each time. They arrived at it separately and unequally --
`ik_channels` hid the mesh objects, `component_matching` disabled only their
Armature modifiers. Hiding is the stronger of the two, because `hide_viewport`
drops the mesh out of the dependency graph entirely while muting one modifier
still evaluates the rest of the stack.

Hiding is also the riskier of the two, and that is why this module exists
rather than one caller importing the other's helper. A mesh that something
still reads has to stay in the graph, so `deferrable` refuses any mesh the
armature itself references through a constraint or a driver, on top of the
visibility-animation rules the IK path already applied.

That guard covers the direct feedback path -- the armature reading a mesh it
would otherwise hide. It does not chase indirect chains (a second mesh
shrinkwrapped to the first, feeding a constraint back into the rig). The IK
caller additionally proves the whole rig is one closed dependency island
before enabling this at all; `component_matching` has no such proof, so treat
its use as "safe for the references we can see from the armature".
"""
from contextlib import contextmanager


def _armature_reads(obj, mesh):
    """True when the armature references `mesh`, so hiding it changes the pose."""
    for holder in (obj, *obj.pose.bones):
        for con in holder.constraints:
            for prop in ('target', 'pole_target', 'space_object'):
                if getattr(con, prop, None) == mesh:
                    return True
    for animation in (obj.animation_data, obj.data.animation_data):
        for curve in (animation.drivers if animation else ()):
            for variable in curve.driver.variables:
                for target in variable.targets:
                    if target.id == mesh or target.id == mesh.data:
                        return True
    return False


def deferrable(context, obj):
    """`(mesh, visibility_drivers)` for each mesh whose evaluation can be skipped.

    Never touches a linked mesh, a mesh whose visibility is animated by the
    user, or a mesh the armature reads. The visibility drivers handed back are
    the add-on's own imported-Smash ones, which the caller mutes so hiding the
    mesh is not immediately undone by its own driver.
    """
    from ..anim.fcurve_compat import get_all_action_fcurves
    found = []
    for mesh in context.scene.objects:
        if (mesh.type != 'MESH' or mesh.library is not None
                or (mesh.parent != obj and not any(
                    mod.type == 'ARMATURE' and mod.object == obj
                    for mod in mesh.modifiers))):
            continue
        animation = mesh.animation_data
        visibility = []
        if animation:
            if animation.nla_tracks or (animation.action and any(
                fc.data_path == 'hide_viewport'
                for fc in get_all_action_fcurves(animation.action, id_type='OBJECT')
            )):
                continue
            visibility = [fc for fc in animation.drivers if fc.data_path == 'hide_viewport']
            # Imported Smash visibility is pure armature-property input.
            # Leave custom visibility drivers entirely alone.
            safe = True
            for fc in visibility:
                driver = fc.driver
                if driver.type != 'SCRIPTED' or len(driver.variables) != 1:
                    safe = False
                    break
                var = driver.variables[0]
                target = var.targets[0]
                if (var.type != 'SINGLE_PROP' or target.id != obj.data
                        or not target.data_path.startswith('sub_anim_properties.vis_track_entries[')
                        or not target.data_path.endswith('].value')
                        or driver.expression != '1 - ' + var.name):
                    safe = False
                    break
            if not safe:
                continue
        if _armature_reads(obj, mesh):
            continue
        found.append((mesh, visibility))
    return found


def defer(meshes):
    """Hide `meshes`, returning the state `restore` needs to put them back."""
    state = []
    for mesh, visibility in meshes:
        muted = [(fc, fc.mute) for fc in visibility]
        for fc in visibility:
            fc.mute = True
        state.append((mesh, mesh.hide_viewport, muted))
        mesh.hide_viewport = True
    return state


def restore(state):
    """Put every deferred mesh back, in reverse order.

    Tolerates an object deleted mid-match: the match is what owns the failure,
    and raising here would replace its error with a ReferenceError.
    """
    for mesh, value, muted in reversed(state):
        for fc, mute in reversed(muted):
            try:
                fc.mute = mute
            except ReferenceError:
                pass
        try:
            mesh.hide_viewport = value
        except ReferenceError:
            pass


@contextmanager
def deferred(context, obj, enabled=True):
    """Scope the deferral. The caller restores the frame and evaluates after."""
    state = defer(deferrable(context, obj)) if enabled else []
    try:
        yield
    finally:
        restore(state)
