from pathlib import Path
from types import SimpleNamespace

fixture = Path(__file__).with_name('test_addon_registration_blender.py')
exec(compile(fixture.read_text().split('floor = importlib.import_module')[0], str(fixture), 'exec'))
properties = importlib.import_module(MODULE + '.expy_kit.properties')
ui = importlib.import_module(MODULE + '.expy_kit.ui')


def make_rig(name):
    obj = bpy.data.objects.new(name, bpy.data.armatures.new(name))
    bpy.context.collection.objects.link(obj)
    return obj


first = make_rig('Custom First')
second = make_rig('Custom Second')
bpy.context.view_layer.objects.active = first
custom = first.data.expykit_retarget.custom
other = second.data.expykit_retarget.custom
custom.add_bone('first_custom', 'FirstBone')
assert other.get_bones() == []
other.add_bone('second_custom', 'SecondBone')
assert custom.get_bones() == [('first_custom', 'FirstBone')]
assert bpy.ops.object.expy_kit_remove_custom_bone(identifier='first_custom') == {'FINISHED'}
assert not custom.entries and custom.get_bones() == []
custom.migrate_legacy_bones()
assert not custom.entries
# Simulate defaults left by an older add-on version in this Blender session.
setattr(properties.RetargetCustom, 'old_shared_default', bpy.props.StringProperty(default='GhostBone'))
assert custom.get_bones() == []
custom.migrate_legacy_bones()
assert not custom.entries
# Saved legacy values remain visible on rigs that have not migrated yet.
legacy_rig = make_rig('Legacy Custom')
bpy.context.view_layer.objects.active = legacy_rig
custom = legacy_rig.data.expykit_retarget.custom
custom['saved_legacy'] = 'LegacyBone'
assert custom.get_bones() == [('saved_legacy', 'LegacyBone')]
assert not custom.entries


class Layout:
    def row(self, **kwargs):
        return self

    def label(self, **kwargs):
        pass

    def operator(self, *args, **kwargs):
        return SimpleNamespace()


def forbidden_migration(self):
    raise AssertionError('Panel drawing must never migrate stored data')


original = properties.RetargetCustom.migrate_legacy_bones
properties.RetargetCustom.migrate_legacy_bones = forbidden_migration
try:
    ui.VIEW3D_PT_expy_retarget_custom.draw(SimpleNamespace(layout=Layout()), bpy.context)
finally:
    properties.RetargetCustom.migrate_legacy_bones = original
assert not custom.entries
assert bpy.ops.object.expy_kit_remove_custom_bone(identifier='saved_legacy') == {'FINISHED'}
assert custom.get_bones() == []
ui.VIEW3D_PT_expy_retarget_custom.draw(SimpleNamespace(layout=Layout()), bpy.context)
assert not custom.entries
assert other.get_bones() == [('second_custom', 'SecondBone')]
# Old files can retain raw aliases for rows deleted before this fix.
custom['stale_alias'] = 'DeletedBone'
assert custom.entries_initialized
assert custom.get_bones() == []
custom.migrate_legacy_bones()
assert not custom.entries
ui.VIEW3D_PT_expy_retarget_custom.draw(SimpleNamespace(layout=Layout()), bpy.context)
assert not custom.entries
# An old collection without the marker becomes authoritative on the first removal.
custom.entries_initialized = False
entry = custom.entries.add()
entry['identifier'] = 'last_old_row'
entry['bone'] = 'LastBone'
custom['old_deleted_alias'] = 'DeletedEarlier'
assert bpy.ops.object.expy_kit_remove_custom_bone(identifier='last_old_row') == {'FINISHED'}
assert custom.entries_initialized and not custom.entries
assert custom.get_bones() == []
custom.migrate_legacy_bones()
assert not custom.entries
print('EXPY CUSTOM LAST REMOVAL PASSED')
