"""The Collision Shapes panel lists every shape type, filters by type, and Add fills in sensible defaults."""
from pathlib import Path
from types import SimpleNamespace

fixture = Path(__file__).with_name('test_addon_registration_blender.py')
exec(compile(fixture.read_text(encoding='utf-8').split('floor = importlib.import_module')[0], str(fixture), 'exec'))
ui = importlib.import_module(MODULE + '.source.swing.ui')
operators = importlib.import_module(MODULE + '.source.swing.operators')
operators.add_hash_to_param_labels = lambda *_args, **_kwargs: None  # keep ParamLabels.csv untouched
panel = ui.SUB_PT_swing_collision_shapes


class Recorder:
    def __init__(self, log):
        object.__setattr__(self, 'log', log)

    def __setattr__(self, key, value):
        self.log.append(('set', key, value))

    def __getattr__(self, method):
        def call(*args, **kwargs):
            self.log.append((method, args, kwargs))
            return Recorder(self.log)
        return call


def draw(obj):
    log = []
    proxy = SimpleNamespace(layout=Recorder(log), **{n: getattr(panel, n) for n in dir(panel) if n.startswith('draw_') and n != 'draw'})
    panel.draw(proxy, SimpleNamespace(object=obj, scene=bpy.context.scene))
    return log


def labels(log):
    return [entry[2].get('text', '') for entry in log if entry[0] == 'label']


arma = bpy.data.armatures.new('ShapesTest')
obj = bpy.data.objects.new('ShapesTest', arma)
bpy.context.scene.collection.objects.link(obj)
bpy.context.view_layer.objects.active = obj
obj.select_set(True)
ssd = arma.sub_swing_data

assert hasattr(bpy.types, 'SUB_PT_swing_collision_shapes')
assert not hasattr(bpy.types, 'SUB_PT_swing_data_spheres'), 'the six old panels are replaced'
assert any('No collision shapes yet' in text for text in labels(draw(obj)))

for name in ('head', 'hip'):
    ssd.spheres.add().name = name
ssd.spheres[0].bone = 'J_Head'
capsule = ssd.capsules.add()
capsule.name, capsule.start_bone_name, capsule.end_bone_name = 'neck', 'J_Neck', 'J_Head'

log = draw(obj)
selects = [e for e in log if e[0] == 'operator' and e[1][0] == 'sub.swing_shape_select']
assert [e[2]['text'] for e in selects] == ['head', 'hip', 'neck'], selects
assert 'J_Head' in labels(log) and 'J_Neck → J_Head' in labels(log)
assert any(e[0] == 'prop_enum' and e[2].get('text') == 'All 3' for e in log)
assert ('menu', ('SUB_MT_swing_shape_add',), {'text': '', 'icon': 'ADD'}) in log
assert not any(e[0] == 'operator' and e[1][0].endswith('_add') and e[1][0].startswith('sub.swing_data_') for e in log), 'no popups from the panel'

ssd.shape_filter = 'CAPSULE'
assert ssd.active_shape_type == 'CAPSULE', 'filtering to a type selects that type'
log = draw(obj)
assert any(e[0] == 'template_list' and e[1][3] == 'capsules' for e in log), log
assert not any(e[0] == 'operator' and e[1][0] == 'sub.swing_shape_select' for e in log)
ssd.shape_filter = 'ALL'

with bpy.context.temp_override(object=obj, active_object=obj):
    assert bpy.ops.sub.swing_shape_select(shape_type='SPHERE', index=1) == {'FINISHED'}
assert ssd.active_shape_type == 'SPHERE' and ssd.active_sphere_index == 1
assert any(e[0] == 'prop' and e[1][1] == 'radius' for e in draw(obj))

# Add with no name: the name comes from the bone and the shape collides with the active swing bone.
bpy.ops.object.mode_set(mode='EDIT')
for name, head, tail in (('J_Head', (0, 0, 0), (0, 0, 1)), ('S_Hair1', (0, 0, 1), (0, 0, 2))):
    bone = arma.edit_bones.new(name)
    bone.head, bone.tail = head, tail
bpy.ops.object.mode_set(mode='OBJECT')
chain = ssd.swing_bone_chains.add()
chain.name = 'hair'
chain.swing_bones.add().name = 'S_Hair1'
ssd.spheres.clear()
ssd.capsules.clear()
with bpy.context.temp_override(object=obj, active_object=obj):
    result = bpy.ops.sub.swing_data_sphere_add('EXEC_DEFAULT', sphere_name='', bone_name='J_Head', radius=2.0)
assert result == {'FINISHED'}, result
assert [s.name for s in ssd.spheres] == ['j_head']
assert ssd.active_shape_type == 'SPHERE'
collisions = chain.swing_bones[0].collisions
assert [(c.collision_type, c.collision_index) for c in collisions] == [('SPHERE', 0)]
assert operators._unique_shape_name(ssd.spheres, 'j_head') == 'j_head_1'

# Chain and bone rows show which shape types they collide with.
icon_log = []
ui.draw_collision_icons(Recorder(icon_log), ui.chain_collision_kinds(chain))
assert [e[2]['icon'] for e in icon_log if e[0] == 'label'] == ['SPHERE'], icon_log
icon_log.clear()
ui.draw_collision_icons(Recorder(icon_log), ['SPHERE', 'CAPSULE', 'SPHERE', 'PLANE', 'OVAL', 'SPHERE'])
shown = [e[2] for e in icon_log if e[0] == 'label']
assert [x.get('icon') for x in shown[:4]] == ['SPHERE', 'META_CAPSULE', 'SPHERE', 'MESH_PLANE'], shown
assert shown[4]['text'] == '+2', shown

# Attach buttons appear only for bones that don't collide yet.
chain.swing_bones.add().name = 'S_Hair2'
chain.active_swing_bone_index = 0
ssd.shape_filter = 'ALL'
ssd.active_shape_type, ssd.active_sphere_index = 'SPHERE', 0


def attach_buttons():
    return [e[2]['text'] for e in draw(obj) if e[0] == 'operator' and e[1][0] == 'sub.swing_shape_attach']


assert attach_buttons() == ['Collide with chain hair'], 'S_Hair1 already collides, S_Hair2 does not'
chain.active_swing_bone_index = 1
assert attach_buttons() == ['Collide with S_Hair2', 'Collide with chain hair']
with bpy.context.temp_override(object=obj, active_object=obj):
    assert bpy.ops.sub.swing_shape_attach(shape_type='SPHERE', index=0, whole_chain=True) == {'FINISHED'}
assert [[(c.collision_type, c.collision_index) for c in b.collisions] for b in chain.swing_bones] == [[('SPHERE', 0)]] * 2
assert attach_buttons() == []

# Adding fills in a form inside the panel instead of opening a popup.
draft = ssd.shape_draft
ssd.spheres.clear()
for b in chain.swing_bones:
    b.collisions.clear()
chain.active_swing_bone_index = 0
with bpy.context.temp_override(object=obj, active_object=obj):
    assert bpy.ops.sub.swing_shape_add_start(shape_type='SPHERE') == {'FINISHED'}
assert draft.adding == 'SPHERE' and draft.radius == 1.0 and draft.attach_to_bone
log = draw(obj)
drawn = [e[1][1] for e in log if e[0] in {'prop', 'prop_search'} and e[1][0] == draft]
assert drawn == ['bone_name', 'name', 'offset', 'radius', 'attach_to_bone', 'attach_to_chain'], drawn
assert ('set', 'enabled', False) in log, 'Add stays greyed out until a bone is chosen'
assert not any(e[0] == 'prop' and e[1][0] != draft and e[1][1] == 'radius' for e in log), 'selected-shape fields hide while adding'

with bpy.context.temp_override(object=obj, active_object=obj):
    assert bpy.ops.sub.swing_shape_add_confirm() == {'CANCELLED'}, 'no bone chosen yet'
    assert draft.adding == 'SPHERE', 'the form stays open so nothing typed is lost'
    draft.bone_name, draft.name, draft.radius = 'J_Head', '', 3.0
    assert bpy.ops.sub.swing_shape_add_confirm() == {'FINISHED'}
assert draft.adding == 'NONE'
assert [(s.name, s.bone, s.radius) for s in ssd.spheres] == [('j_head', 'J_Head', 3.0)]
assert [(c.collision_type, c.collision_index) for c in chain.swing_bones[0].collisions] == [('SPHERE', 0)]

with bpy.context.temp_override(object=obj, active_object=obj):
    bpy.ops.sub.swing_shape_add_start(shape_type='CAPSULE')
    assert bpy.ops.sub.swing_shape_add_cancel() == {'FINISHED'}
assert draft.adding == 'NONE' and len(ssd.capsules) == 0

print('SWING_COLLISION_SHAPES_OK')
