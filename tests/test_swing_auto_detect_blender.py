"""Auto-detect writes ParamLabels.csv once and still gives every chain a unique name."""
from pathlib import Path

fixture = Path(__file__).with_name('test_addon_registration_blender.py')
exec(compile(fixture.read_text(encoding='utf-8').split('floor = importlib.import_module')[0], str(fixture), 'exec'))
labels = importlib.import_module(MODULE + '.source.param_labels')
pyprc = importlib.import_module(MODULE + '.dependencies.pyprc')

csv_path = Path(profile.name) / 'ParamLabels.csv'
csv_path.write_text('0x0000000000,placeholder\n', encoding='utf-8')
labels.labels_path = lambda: csv_path
labels.ensure_param_labels = lambda: csv_path
writes = []
real_append = labels._append_entries
labels._append_entries = lambda path, entries: writes.append(len(entries)) or real_append(path, entries)

arma = bpy.data.armatures.new('AutoDetect')
obj = bpy.data.objects.new('AutoDetect', arma)
bpy.context.scene.collection.objects.link(obj)
bpy.context.view_layer.objects.active = obj
obj.select_set(True)
bpy.ops.object.mode_set(mode='EDIT')
for chain in ('A', 'B'):
    parent = None
    for i, name in enumerate((f'S_Hair{chain}1', f'S_Hair{chain}2', f'S_Hair{chain}2_null')):
        bone = arma.edit_bones.new(name)
        bone.head, bone.tail = (ord(chain), i, 0), (ord(chain), i + 1, 0)
        bone.parent = parent
        parent = bone
bpy.ops.object.mode_set(mode='OBJECT')

# A hand-made chain already uses the name auto-detect would pick for S_HairA1.
ssd = arma.sub_swing_data
ssd.swing_bone_chains.add()['name'] = 'haira1'

with bpy.context.temp_override(object=obj, active_object=obj):
    assert bpy.ops.sub.swing_bone_chain_auto_detect() == {'FINISHED'}

names = [chain.name for chain in ssd.swing_bone_chains]
assert names == ['haira1', 'haira1.001', 'hairb1'], names
assert len(writes) == 1, f'expected one batched CSV write, got {len(writes)}'
rows = csv_path.read_text(encoding='utf-8').splitlines()
for label in ('haira1.001', 'hairb1', 's_haira1', 's_haira2', 's_haira2col'):
    assert f'{pyprc.hash(label)},{label}' in rows or any(row.endswith(',' + label) for row in rows), label
print('SWING_AUTO_DETECT_OK')
