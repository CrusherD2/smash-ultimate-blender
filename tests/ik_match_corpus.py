"""The fixtures the acceptance gate is run against.

The prior evidence was ten rig configurations of a single animation, which
varies the rig and never the motion. This corpus adds one genuinely distinct
animation (the generated near-straight clip, same rig) plus one genuinely
distinct rig (Shy Guy, a different 170-bone production skeleton).

The corpus therefore contains TWO distinct animations, not three: `shyguy_static`
is a static pose (see its own comment below for why), so it contributes rig-shape
diversity only, not motion diversity. Do not describe it as a third clip.

A fixture that is not present locally is skipped, not failed: the large .blend
files live under .tests/ and are not distributed.
"""
from pathlib import Path
import os

ROOT = Path(__file__).resolve().parents[1]
BENCH = ROOT / '.tests' / 'benchmarks'
NEAR_STRAIGHT = BENCH / 'ik_corpus' / 'near_straight.blend'

# The ten configurations the existing matrix uses. Kept as the default set so a
# widened corpus is a superset of the published evidence, never a replacement.
FULL = [('normal', 'BOTH'), ('normal', 'ARMS'), ('normal', 'LEGS'),
        ('object_scale', 'BOTH'), ('parent_scale', 'BOTH'), ('inheritance', 'BOTH'),
        ('stretch', 'BOTH'), ('arm_pull', 'BOTH'), ('animated_stretch', 'BOTH'),
        ('foot_controls', 'BOTH')]
# Secondary fixtures carry a reduced set: distinct motion is the variable being
# added, and repeating all ten on every clip multiplies runtime without
# multiplying evidence.
LIGHT = [('normal', 'BOTH'), ('parent_scale', 'BOTH'), ('stretch', 'BOTH')]

SOURCES = [
    {'name': 'baseline',      'blend': BENCH / 'ik_apply/out/baseline.blend',           'configurations': FULL},
    {'name': 'near_straight', 'blend': NEAR_STRAIGHT,                                    'configurations': LIGHT},
    # matched_wait.blend (the brief's original pick) already has leg IK built and
    # matched: run_variant's create_controls()+match() is then a no-op against it
    # (verified: exactly 0.0 total residual over 240 frames, not the small nonzero
    # floating-point residual a real match leaves).
    #
    # The obvious fix -- save a state with the wait animation imported but the
    # legs not yet re-matched -- was tried and abandoned: it requires
    # rig._set_ik_enabled() to actually engage the IK/FK blend constraint, and
    # that call is a no-op until armature_has_ik() already recognises the rig,
    # which it does not immediately after create_foot_ik(match_position=False).
    # Verified directly (printed LegL's world position before/after
    # create_controls() and an explicit match(): bit-identical either way).
    #
    # So this source is kept as what it verifiably is, per this task's own
    # documented fallback: shyguy_static.blend is fresh_foot_ik.blend (legs
    # genuinely unmatched -- 0.000137 total residual over its original 250
    # frames, confirming the solver does real work) with its frame range
    # trimmed to 5, since it carries a STATIC pose (fresh_foot_ik.blend is saved
    # in tests/reproduce_shyguy_ik_blender.py before any animation is imported,
    # so all 250 of its original frames are the same pose -- confirmed by
    # decompressing both fixtures and searching for the animation's action name,
    # 'a00wait': 4 hits in matched_wait.blend, 0 in fresh_foot_ik.blend).
    # This source contributes a different 170-bone rig shape, not different
    # motion -- see the module docstring.
    {'name': 'shyguy_static', 'blend': BENCH / 'ik_corpus/shyguy_static.blend',          'configurations': [('normal', 'LEGS')]},
]


def available():
    override = os.environ.get('SUB_IK_CORPUS')
    wanted = set(override.split(',')) if override else None
    return [s for s in SOURCES if s['blend'].exists()
            and (wanted is None or s['name'] in wanted)]
