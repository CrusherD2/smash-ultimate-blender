"""Trim fresh_foot_ik.blend's frame range for the corpus.

Reviewer finding: fresh_foot_ik.blend (tests/reproduce_shyguy_ik_blender.py) is
saved before any animation is ever imported, so its "250 frames" is Blender's
default new-scene frame_end, not a clip length -- the pose is static and
identical on every one of those 250 frames.

Tried and abandoned: building a variant with the wait animation imported but
legs not yet re-matched (see tests/reproduce_shyguy_ik_blender.py:38-45 for
the enable-IK step). rig._set_ik_enabled() only sets sub_use_ik_legs when
armature_has_ik() already recognises the rig as IK-equipped, and immediately
after create_foot_ik(match_position=False) that check does not yet pass, so
the constraint influence never actually engages -- the observed LegL/KneeL/
FootL bones stayed driven purely by FK regardless of match(), verified by
printing their world position before and after both create_controls() and an
explicit match() call (bit-identical). Per this task's own instruction not to
fight an import pipeline that won't separate cleanly, this fixture is instead
kept as what it verifiably is: a different 170-bone production rig with a
static pose, contributing rig-shape diversity and no motion diversity. Its
frame range is trimmed here so the corpus doesn't inflate "frames compared"
with 250 copies of one pose.
"""
from pathlib import Path
fixture = Path(__file__).with_name('test_addon_registration_blender.py')
exec(compile(fixture.read_text().split('addon_utils.disable(MODULE')[0], str(fixture), 'exec'))

SRC = ROOT / '.tests/benchmarks/shyguy_ik_repro/fresh_foot_ik.blend'
OUT = ROOT / '.tests/benchmarks/ik_corpus/shyguy_static.blend'
assert SRC.exists(), SRC
bpy.ops.wm.open_mainfile(filepath=str(SRC))
scene = bpy.context.scene
scene.frame_end = scene.frame_start + 4  # 5 frames of one static pose is enough to prove no crash
OUT.parent.mkdir(parents=True, exist_ok=True)
bpy.ops.wm.save_as_mainfile(filepath=str(OUT))
print(f'SHYGUY_STATIC_FIXTURE_OK {OUT} frames={scene.frame_end - scene.frame_start + 1}')
