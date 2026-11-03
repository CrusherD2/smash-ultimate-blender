"""Name parsing for VIS shape outliner groups. No Blender required."""
import importlib.util
import sys
import types
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _load():
    bpy = types.ModuleType("bpy")
    bpy.__path__ = []
    bpy_types = types.ModuleType("bpy.types")
    bpy_types.Operator = type("Operator", (), {})
    bpy.types = bpy_types
    mathutils = types.ModuleType("mathutils")
    mathutils.Matrix = type("Matrix", (), {"Identity": staticmethod(lambda _size: None)})
    sys.modules["bpy"] = bpy
    sys.modules["bpy.types"] = bpy_types
    sys.modules["mathutils"] = mathutils
    spec = importlib.util.spec_from_file_location(
        "vis_shape_groups_unit",
        ROOT / "source" / "model" / "vis_shape_groups.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


groups = _load()


class VisShapeGroupNameTests(unittest.TestCase):
    def test_duplicate_suffixes_share_one_group(self):
        names = [
            "baseform_Angry_VIS_O_OBJShape",
            "baseform_Angry_VIS_O_OBJShape.001",
            "baseform_Angry_VIS_O_OBJShape.002",
        ]
        self.assertEqual(
            {groups.vis_shape_group_name(name) for name in names},
            {"baseform_Angry"},
        )

    def test_flip_and_other_expressions_stay_separate(self):
        self.assertEqual(
            groups.vis_shape_group_name("baseform_ConfidentFLIP_VIS_O_OBJShape.001"),
            "baseform_ConfidentFLIP",
        )
        self.assertEqual(
            groups.vis_shape_group_name("angelHalo_VIS_O_OBJShape"),
            "angelHalo",
        )

    def test_case_and_repeated_blender_suffix(self):
        self.assertEqual(
            groups.vis_shape_group_name("baseform_angry_vis_o_objshape.001.002"),
            "baseform_angry",
        )

    def test_non_vis_meshes_are_not_grouped(self):
        self.assertIsNone(groups.vis_shape_group_name("c00BodyShape"))
        self.assertIsNone(groups.vis_shape_group_name("_VIS_O_OBJShape"))
        self.assertIsNone(groups.vis_shape_group_name("baseform_Angry_VIS_O_OBJShape_extra"))


if __name__ == "__main__":
    unittest.main()
