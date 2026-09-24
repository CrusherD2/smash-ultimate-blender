"""Sort dropped Smash files into the importers that should handle them.

Pure Python (no bpy) so the routing rules can be tested outside Blender.
"""
import os
import re
from dataclasses import dataclass, field

MODEL_SUFFIXES = ('.numdlb', '.numshb', '.nusktb', '.numatb', '.nuhlpb')
ANIM_SUFFIX = '.nuanmb'
RAW_ANIM_SUFFIX = '.rawanim'
SHPC_SUFFIXES = ('.shpcanim', '.shpc')
PRC_SUFFIX = '.prc'

# Every extension the drop handler claims. Blender matches on extension only,
# so anything more specific (swing.prc vs. other params) is decided below.
DROP_EXTENSIONS = MODEL_SUFFIXES + (ANIM_SUFFIX, RAW_ANIM_SUFFIX, PRC_SUFFIX) + SHPC_SUFFIXES

# Stage lighting ships as light.nuanmb / light00.nuanmb, usually under a light/
# folder. Fighter motions never use either, so this cannot steal a real motion.
_LIGHT_NAME = re.compile(r'^light\d*\.nuanmb$', re.IGNORECASE)


@dataclass
class DropPlan:
    model_folders: list = field(default_factory=list)
    animations: list = field(default_factory=list)
    swing_files: list = field(default_factory=list)
    stage_lights: list = field(default_factory=list)
    shpc_files: list = field(default_factory=list)
    skipped: list = field(default_factory=list)

    @property
    def needs_armature(self):
        return bool(self.animations or self.swing_files)

    def is_empty(self):
        return not (self.model_folders or self.animations or self.swing_files
                    or self.stage_lights or self.shpc_files)


def is_stage_light_anim(path):
    name = os.path.basename(path)
    if not name.lower().endswith(ANIM_SUFFIX):
        return False
    parent = os.path.basename(os.path.dirname(path)).lower()
    return bool(_LIGHT_NAME.match(name)) or parent == 'light'


def plan_drop(paths):
    """Group dropped paths by importer, dropping duplicates and keeping drop order.

    Any model file stands for its whole folder, so dropping one .numdlb or
    selecting every file of a model imports that model exactly once.
    """
    plan = DropPlan()
    seen = set()

    def add_once(bucket, value):
        key = os.path.normcase(os.path.normpath(value))
        if key not in seen:
            seen.add(key)
            bucket.append(value)

    for path in paths:
        if not path:
            continue
        lower = path.lower()
        name = os.path.basename(lower)
        if lower.endswith(MODEL_SUFFIXES):
            add_once(plan.model_folders, os.path.dirname(path))
        elif lower.endswith(ANIM_SUFFIX):
            add_once(plan.stage_lights if is_stage_light_anim(path) else plan.animations, path)
        elif lower.endswith(RAW_ANIM_SUFFIX):
            add_once(plan.animations, path)
        elif lower.endswith(SHPC_SUFFIXES):
            add_once(plan.shpc_files, path)
        elif lower.endswith(PRC_SUFFIX) and 'swing' in name:
            add_once(plan.swing_files, path)
        else:
            add_once(plan.skipped, path)
    return plan
