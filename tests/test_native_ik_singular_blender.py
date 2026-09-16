"""Exact-axis, straight, folded-target and zero-distance compatibility cases."""
from pathlib import Path
from mathutils import Matrix

setup=Path(__file__).with_name('test_native_ik_synthetic_blender.py')
exec(compile(setup.read_text().split('rng=random.Random')[0],str(setup),'exec'))
from native_ik_runtime import Request, evaluate_steps
bpy.ops.object.mode_set(mode='EDIT')
data.edit_bones['upper'].head=(0,1,0)
data.edit_bones['upper'].tail=(0,3,0)
data.edit_bones['lower'].head=(0,3,0)
data.edit_bones['lower'].tail=(0,5,0)
bpy.ops.object.mode_set(mode='OBJECT')
accepted=fallbacks=0
failures=[]
os.environ['SUB_NATIVE_IK']='1'
for bend in (0.0, 1e-7, 1e-5, 1e-4, 1e-3, .01, .1):
    obj.pose.bones['lower'].rotation_mode='XYZ'
    obj.pose.bones['lower'].rotation_euler.z=bend
    for target in ((0,5,0),(0,4,0),(0,7,0),(0,1,0),(1,4,0),(0,4,1),(0,-1,0)):
        con.mute=True
        obj.pose.bones['target'].matrix=Matrix.Translation(target)
        obj.pose.bones['pole'].matrix=Matrix.Translation((1,3,0))
        bpy.context.view_layer.update()
        native=Solver(obj,None,bones,con,0)
        con.mute=False
        try:
            for angle in (0.0,.35,-.75,1.5707963267948966,-3.141592653589793):
                con.pole_angle=angle
                bpy.context.view_layer.update()
                actual=native.solve(con.pole_angle)
                if actual is None:
                    fallbacks+=1
                else:
                    accepted+=1
                    error=max(abs(a-b) for mat,bone in zip(actual,bones)
                              for row_a,row_b in zip(mat,bone.matrix) for a,b in zip(row_a,row_b))
                    if error:
                        differences = [dict(bone=bone.name,row=r,column=c,native=a,blender=b,
                                            absolute_error=abs(a-b))
                                       for mat,bone in zip(actual,bones)
                                       for r,(ra,rb) in enumerate(zip(mat,bone.matrix))
                                       for c,(a,b) in enumerate(zip(ra,rb)) if a != b]
                        failures.append(dict(bend=bend,target=target,angle=angle,error=error,
                                             elements=differences))
                # Verification mode must preserve the Blender matrices even
                # for native candidates that incorrectly report convergence.
                expected=[b.matrix.copy() for b in bones]
                request=Request(native,con.pole_angle)
                def step():
                    yield request
                evaluate_steps(bpy.context,[step()],True)
                assert all(tuple(a)==tuple(b) for proposed,observed in zip(request.matrices,expected)
                           for a,b in zip(proposed,observed))
        finally:
            native.close()
report=dict(native_candidates=accepted,geometry_or_iteration_fallbacks=fallbacks,
            native_mismatches=failures,verified_exact=accepted+fallbacks,blender=bpy.app.version_string)
path=Path(__file__).resolve().parents[1]/'.tests/benchmarks/native_ik'/f'singular_{bpy.app.version[0]}.{bpy.app.version[1]}.json'
path.write_text(json.dumps(report,indent=2))
print('NATIVE_SINGULAR_VERIFIED',report)
