# Independent IK and FK

Create legs, arms, or both from IK Tools or Animation Rig. Creation matches the current FK pose and inserts an IK mode key at the current frame for the created limbs. The controls are ready to use immediately. Accept the optional match dialog to copy the full FK animation to IK. FK transform keys are preserved.

Switch to FK or Switch to IK keys only that destination at the current frame, for the selected limbs. Place opposite mode keys on different frames to blend between them. Switching does not rematch or overwrite edited controls.

IK Stretch Arms / IK Stretch Legs in the IK controls is off by default. Hands and feet retain their solved position when a target is out of reach. Enable it to let the endpoint follow the target's position. Clicking a stretch button inserts or updates a stepped state key in the same SAP action as the FK/IK switches, even with Auto Key disabled. Scrubbing restores that state. Newly created target and pole controls have no parent; internal solver bones retain their chain hierarchy. Existing independent rigs have their endpoint constraints repaired when the addon loads, without rematching animation.

Enable **Stretch Chain** beside an IK Stretch control to distribute the target's positional offset across the full parent chain without adding scale. The root remains anchored and the displacement increases toward the endpoint. With arm chain stretch enabled, each ArmIK pole has its own keyframable **Pull** influence: zero retains normal pole-only behavior and one pulls that chain's bend bone fully toward its ArmIK control. Left, right, extra, and custom arm chains are independent.

Under **Create IK Controls**, expand **Custom IK Bones**. Choose a setup name, root, bend bone, endpoint, and Arms/Legs switch group. The bones must lie on one parent path and cannot overlap another IK setup. Custom chains participate in matching, switching, and Bake & Remove IK. Presets are stored as JSON in Blender's version-specific user scripts directory under `presets/smash_custom_ik`.

Matching samples the scene frame range. A newly loaded action, newly created controls, or an unmatched limb makes the match button appear. Matching only one frame does not mark the entire animation matched. Rematch after changing the source FK animation if you want those changes copied into IK. Matching keys the hidden solver with the FK rotations and places the target and pole where that pose is already solved, so IK reproduces FK 1:1 on every matched frame, twist included, with nothing to fade out when you edit a control. On frames where a limb is less than 1% bent, the hidden solver is bent very slightly toward its pole (never the original bones) so it folds the right way when you move the control; those frames can differ from FK by up to about 1.5 degrees.

Position IK Controls evaluates independent limbs together to reduce scene updates, including when Entire Animation is enabled. Solver iterations, pole fitting precision, and keyframe sampling are unchanged. Rigs with external or cross-limb dependencies, unsupported drivers, or animated constraint settings use sequential matching. Interactive pose-tool refreshes are deferred until matching finishes.

Bake & Remove IK allows selecting legs, arms, or all present IK. It samples the evaluated motion before removing those controls and preserves unrelated limb channels.

## Existing scenes

Restart Blender after updating the addon. Use Match IK to Current Animation for existing controls to migrate them to independent solver chains. Keep a saved copy of the scene before migrating. The original FK keys remain intact; migration replaces the old constraints on the selected limb chains.

## Implementation and checks

Hidden, nondeforming `BL_SUB_IK_` bones are an exact copy of the limb with one IK constraint on its end bone. When FK slides a joint with location keys, matching turns and scales the hidden bones so they pass through the same joints, and hidden `BL_SUB_IK_OFS_` bones store the small rotation back to FK. `BL_SUB_IK_POSE_` bones take those rotations and re-add the FK location keys, which Blender's IK ignores. `BL_SUB_IK_PULL_` bones exist for Stretch, Stretch Chain, Arm Pull and Progressive Scale and only carry constraints while one of those is on or animated. Each original bone has a single driven constraint that blends it to this output. Matching keys the solver, target, pole and one pole angle per limb without changing the FK source curves.

The hidden bones have no keys of their own. Matching keys their values as hidden `_IK …` properties on the hand/foot control, and the solver's pole angle as `_IK Pole Angle` on the pole control. Drivers feed those properties into the hidden bones. These curves are listed under the control in the Dope Sheet, so deleting or moving a control's keys also deletes or moves the solver keys for those frames, and the limb interpolates instead of keeping stale solver keys. Rigs matched before this change show **Update IK Rig**, which moves the existing keys onto the controls without changing the pose and keeps a backup.

Run `blender --background --factory-startup --python-exit-code 1 --python tests/ik_regression.py`. An optional `-- path/to/character.blend` loads only an armature datablock for the stress test; it never saves the fixture.

Tests cover each creation path and limb selection, integer-frame pose accuracy, independence in both directions, explicit switch keys, interpolation, action match tracking, and scoped baking/removal. Stress tests cover straight chains and large twists. Subframe matching and arbitrary third-party constraints are not covered by these tests.
