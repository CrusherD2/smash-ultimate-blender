"""The fixtures the acceptance gate is run against.

The prior evidence was ten rig configurations of a single animation, which
varies the rig and never the motion. This adds distinct motion and a distinct
rig, plus the generated near-straight worst case.

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
    # floating-point residual a real match leaves). fresh_foot_ik.blend has the legs
    # still unmatched, so the same run actually exercises the solver (verified:
    # 0.000137 total residual over 250 frames) -- swapped in per the task's own
    # fallback instruction.
    {'name': 'shyguy_wait',   'blend': BENCH / 'shyguy_ik_repro/fresh_foot_ik.blend',    'configurations': [('normal', 'LEGS')]},
]


def available():
    override = os.environ.get('SUB_IK_CORPUS')
    wanted = set(override.split(',')) if override else None
    return [s for s in SOURCES if s['blend'].exists()
            and (wanted is None or s['name'] in wanted)]
