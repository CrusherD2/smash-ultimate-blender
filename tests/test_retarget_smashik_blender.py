from pathlib import Path
fixture = Path(__file__).with_name('test_addon_registration_blender.py')
exec(compile(fixture.read_text(encoding='utf-8').split('floor = importlib.import_module')[0], str(fixture), 'exec'))
retarget = importlib.import_module(MODULE + '.source.retargeting')
import shutil
preset_dir = Path(retarget.preset_handler.get_retarget_dir())
preset_dir.mkdir(parents=True, exist_ok=True)
for name in ('SmashUltimate.py', 'SmashIK.py', 'Rigify_Controls.py'):
    shutil.copyfile(Path(__file__).resolve().parents[1] / 'expy_kit/rig_mapping/presets' / name, preset_dir / name)
bpy.ops.object.armature_add()
obj = bpy.context.object
bpy.ops.object.mode_set(mode='EDIT')
hip = obj.data.edit_bones[0]
hip.name = 'Hip'
hip.head, hip.tail = (0, 0, 4), (0, 0, 5)
for side, x in (('L', 1), ('R', -1)):
    for chain in (
        [('Shoulder', (x, 0, 4), (2*x, .1, 4)), ('Arm', (2*x, .1, 4), (3*x, 0, 4)), ('Hand', (3*x, 0, 4), (3.5*x, 0, 4))],
        [('Leg', (x, 0, 4), (x, -.1, 2)), ('Knee', (x, -.1, 2), (x, 0, .5)), ('Foot', (x, 0, .5), (x, -.5, .2)), ('Toe', (x, -.5, .2), (x, -1, .2))],
    ):
        parent = hip
        for prefix, head, tail in chain:
            bone = obj.data.edit_bones.new(prefix + side)
            bone.head, bone.tail, bone.parent = head, tail, parent
            parent = bone
bpy.ops.object.mode_set(mode='OBJECT')
assert retarget.load_preset_with_custom_bones('SmashUltimate.py', obj)
settings = obj.data.expykit_retarget
settings.active_preset = 'Smash.py'
assert not retarget.promote_smash_ik_preset(obj)
# A non-limb value proves creation executes the installed preset, not a hard-coded mapping patch.
with (preset_dir / 'SmashIK.py').open('a') as preset_file:
    print("skeleton.root = 'Hip'", file=preset_file)
settings.root = ''
assert bpy.ops.sub.create_ik_bones(match_position=False) == {'FINISHED'}
assert settings.root == 'Hip'
assert settings.active_preset == 'SmashIK.py'
assert retarget.get_preset_display_label(obj) == 'SmashIK'
for side, suffix in (('left', 'L'), ('right', 'R')):
    arm, leg = getattr(settings, side + '_arm'), getattr(settings, side + '_leg')
    assert (arm.forearm, arm.hand) == ('ArmIK'+suffix, 'HandIK'+suffix)
    assert (leg.leg, leg.foot, leg.toe) == ('KneeIK'+suffix, 'FootIK'+suffix, 'ToeIK'+suffix)
settings.active_preset = 'Custom.py'
settings.left_arm.hand = 'HandL'
assert not retarget.promote_smash_ik_preset(obj)
assert settings.active_preset == 'Custom.py' and settings.left_arm.hand == 'HandL'
assert retarget.load_preset_with_custom_bones('SmashIK.py', obj)
assert settings.left_arm.hand == 'HandIKL'
print('RETARGET_SMASHIK_OK')

assert settings.left_arm.arm == settings.right_arm.arm == ''
assert settings.left_leg.upleg == settings.right_leg.upleg == ''
# Binding must retain cleared slots even if Bind Settings still name the original preset.
bpy.ops.object.mode_set(mode='OBJECT')
source = bpy.data.objects.new('MotionSource', obj.data.copy())
bpy.context.scene.collection.objects.link(source)
scene = bpy.context.scene
scene.expykit_bind_to = source
scene.sub_retarget_apply_to = obj
assert not scene.expykit_bind_by_name
scene.expykit_src_preset = 'SmashUltimate.py'
scene.expykit_trg_preset = 'SmashUltimate.py'
assert bpy.ops.object.ultimate_bind_armatures() == {'FINISHED'}
assert settings.left_arm.arm == settings.right_arm.arm == ''
assert settings.left_leg.upleg == settings.right_leg.upleg == ''
for name in ('ShoulderL', 'ShoulderR', 'LegL', 'LegR'):
    assert not any(getattr(c, 'target', None) == source for c in obj.pose.bones[name].constraints), name
assert scene.expykit_src_preset == scene.expykit_trg_preset == '--Current--'
# Registration must not overwrite a customized installed preset.
import importlib
handler = importlib.reload(retarget.preset_handler)
before = (preset_dir / 'SmashIK.py').read_bytes()
handler.install_presets()
assert (preset_dir / 'SmashIK.py').read_bytes() == before
print('RETARGET_MAPPING_EXCLUSIONS_OK')

# Old saved files may still enable name matching and retain constraints from an earlier bind.
scene.expykit_bind_by_name = True
excluded = ('ShoulderL', 'ShoulderR', 'LegL', 'LegR')
for name in excluded:
    for kind in ('COPY_ROTATION', 'COPY_SCALE'):
        con = obj.pose.bones[name].constraints.new(kind)
        con.target, con.subtarget = source, name + '_RET'
# Unrelated user constraints must survive the cleanup.
user_constraint = obj.pose.bones['ShoulderR'].constraints.new('COPY_ROTATION')
user_constraint.name = 'User rotation'
user_constraint.target, user_constraint.subtarget = source, 'Hip'
assert bpy.ops.object.ultimate_bind_armatures() == {'FINISHED'}
for name in excluded:
    constraints = obj.pose.bones[name].constraints
    assert not any(getattr(c, 'target', None) == source and getattr(c, 'subtarget', '') == name + '_RET'
                   for c in constraints), name
    assert constraints.get('SUB IK Blend') is not None, name
assert obj.pose.bones['ShoulderR'].constraints.get('User rotation') is not None
assert settings.left_arm.arm == settings.right_arm.arm == ''
assert settings.left_leg.upleg == settings.right_leg.upleg == ''
print('RETARGET_IK_EXCLUDED_REBIND_OK')
