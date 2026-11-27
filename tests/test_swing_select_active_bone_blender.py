"""Select Active Bone and Follow Viewport Selection pick the clicked bone in the swing lists."""
from pathlib import Path

fixture = Path(__file__).with_name('test_addon_registration_blender.py')
exec(compile(fixture.read_text(encoding='utf-8').split('floor = importlib.import_module')[0], str(fixture), 'exec'))
operators = importlib.import_module(MODULE + '.source.swing.operators')
operators.add_hash_to_param_labels = lambda *_args, **_kwargs: None
labels = importlib.import_module(MODULE + '.source.param_labels')
csv_path = Path(profile.name) / 'ParamLabels.csv'
csv_path.write_text('0x0000000000,placeholder\n', encoding='utf-8')
labels.labels_path = lambda: csv_path
labels.ensure_param_labels = lambda: csv_path

arma = bpy.data.armatures.new('Follow')
obj = bpy.data.objects.new('Follow', arma)
bpy.context.scene.collection.objects.link(obj)
bpy.context.view_layer.objects.active = obj
obj.select_set(True)
bpy.ops.object.mode_set(mode='EDIT')
root = arma.edit_bones.new('J_Head')
root.head, root.tail = (0, 0, 0), (0, 0, 1)
for chain in ('A', 'B'):
    parent = root
    for i, name in enumerate((f'S_Hair{chain}1', f'S_Hair{chain}2', f'S_Hair{chain}3', f'S_Hair{chain}3_null')):
        bone = arma.edit_bones.new(name)
        bone.head, bone.tail = (ord(chain), i, 1), (ord(chain), i + 1, 1)
        bone.parent = parent
        parent = bone
bpy.ops.object.mode_set(mode='OBJECT')
ssd = arma.sub_swing_data
with bpy.context.temp_override(object=obj, active_object=obj):
    assert bpy.ops.sub.swing_bone_chain_auto_detect() == {'FINISHED'}
assert [c.name for c in ssd.swing_bone_chains] == ['haira1', 'hairb1']
ssd.active_swing_bone_chain_index = 0


def pick(name):
    arma.bones.active = arma.bones[name]
    with bpy.context.temp_override(object=obj, active_object=obj, active_bone=arma.bones[name]):
        return bpy.ops.sub.swing_select_active_bone()


def selected():
    chain = ssd.swing_bone_chains[ssd.active_swing_bone_chain_index]
    return chain.name, chain.swing_bones[chain.active_swing_bone_index].name


assert pick('S_HairB2') == {'FINISHED'} and selected() == ('hairb1', 'S_HairB2')
assert pick('J_Head') == {'CANCELLED'} and selected() == ('hairb1', 'S_HairB2'), 'non-swing bones leave the lists alone'
assert pick('S_HairA3_null') == {'CANCELLED'}
assert operators.select_swing_bone_in_lists(ssd, arma.bones['S_HairA3_null']).endswith('has no swing settings')

# Stale stored indices (e.g. after a chain was removed) fall back to a name search.
arma.bones['S_HairA2'].sub_swing_blender_bone_data.swing_bone_chain_index = 1
assert pick('S_HairA2') == {'FINISHED'} and selected() == ('haira1', 'S_HairA2')
arma.bones['S_HairA1'].sub_swing_blender_bone_data.swing_bone_chain_index = -1
ssd.swing_bone_chains[0].swing_bones[0].name = 'renamed'
assert 'not in a swing bone chain' in operators.select_swing_bone_in_lists(ssd, arma.bones['S_HairA1'])

# Follow: the timer selects the newly active bone once, then leaves list clicks alone.
assert operators.follow_active_bone_timer() == 0.25
arma.bones.active = arma.bones['S_HairB3']
operators.follow_active_bone_timer()
assert selected() == ('haira1', 'S_HairA2'), 'follow is off by default'
ssd.follow_active_bone = True
operators.follow_active_bone_timer()
assert selected() == ('hairb1', 'S_HairB3')
ssd.active_swing_bone_chain_index = 0
operators.follow_active_bone_timer()
assert ssd.active_swing_bone_chain_index == 0, 'picking another chain in the list is not undone'
arma.bones.active = arma.bones['S_HairB1']
operators.follow_active_bone_timer()
assert selected() == ('hairb1', 'S_HairB1')
ssd.follow_active_bone = False
ssd.follow_active_bone = True
ssd.active_swing_bone_chain_index = 0
operators.follow_active_bone_timer()
assert selected() == ('hairb1', 'S_HairB1'), 'turning follow on jumps to the active bone right away'
assert bpy.app.timers.is_registered(operators.follow_active_bone_timer)
print('SWING_SELECT_ACTIVE_BONE_OK')
