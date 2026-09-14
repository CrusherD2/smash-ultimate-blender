"""Reversible visibility for component-owned original bones."""
import json

KEY = 'sub_component_visibility'


def _apply(obj, state):
    desired = set(n for names in state['owners'].values() for n in names)
    for name in desired | set(state['before']):
        pb = obj.pose.bones.get(name)
        if pb is None:
            state['before'].pop(name, None)
            continue
        if name in desired:
            state['before'].setdefault(name, [pb.bone.hide, getattr(pb, 'hide', False)])
            pb.bone['sub_component_hidden'] = True
            pb.bone.hide = True
            if hasattr(pb, 'hide'):
                pb.hide = True
        else:
            old = state['before'].pop(name)
            if 'sub_component_hidden' in pb.bone:
                del pb.bone['sub_component_hidden']
            pb.bone.hide = old[0]
            if hasattr(pb, 'hide'):
                pb.hide = old[1]
    obj[KEY] = json.dumps(state)


def update(obj, c):
    state = json.loads(obj.get(KEY, '{"owners":{},"before":{}}'))
    state['owners'].pop(c.uid, None)
    built = any(b.get('sub_component_id') == c.uid or b.get('sub_face_owner') == c.uid
                for b in obj.data.bones)
    if c.kind == 'IK':
        built = any(r.get('component_id') == c.uid for r in json.loads(obj.get('sub_custom_ik_chains','[]')))
    if getattr(c, 'hide_controlled', False) and built:
        if c.kind == 'IK':
            from .ik_channels import chain_path
            names = chain_path(obj, c.root, c.end, c.middle)
        else:
            names = [b.bone for b in c.bones]
        state['owners'][c.uid] = list(names)
    _apply(obj, state)
    # Persist immediate checkbox edits for Rig Extras and saving/reopening rigs.
    records = json.loads(obj.get('sub_custom_components', '[]'))
    for record in records:
        if record.get('uid') == c.uid:
            record['hide_controlled'] = bool(c.hide_controlled)
    if records:
        obj['sub_custom_components'] = json.dumps(records)


def remove(obj, uid):
    state = json.loads(obj.get(KEY, '{"owners":{},"before":{}}'))
    state['owners'].pop(uid, None)
    _apply(obj, state)


def edit(obj, c, enabled):
    # Face-pose authoring temporarily exposes the original bones.
    if enabled:
        for assignment in c.bones:
            pb = obj.pose.bones.get(assignment.bone)
            if pb:
                pb.bone.hide = False
                if hasattr(pb, 'hide'):
                    pb.hide = False
    elif getattr(c, 'hide_controlled', False):
        update(obj, c)
