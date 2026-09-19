"""Repeatable full-hand benchmark, including pose validation outside the timer.

SUB_BENCH_FRAMES=64, SUB_NATIVE_COMPONENTS=0/1, SUB_BENCH_PROFILE=1.
"""
import os
import cProfile
import pstats
from pathlib import Path
benchmark_frames=int(os.environ.get('SUB_BENCH_FRAMES','64'))
benchmark_fixture=Path(__file__).with_name('test_finger_full_hand_speed_blender.py')
benchmark_source=benchmark_fixture.read_text(encoding='utf-8-sig')
benchmark_source=benchmark_source.replace('scene.frame_start,scene.frame_end=1,8',f'scene.frame_start,scene.frame_end=1,{benchmark_frames}')
benchmark_source=benchmark_source.replace('range(1,9)',f'range(1,{benchmark_frames+1})')
benchmark_source=benchmark_source.replace('obj,1,8,include_fingers',f'obj,1,{benchmark_frames},include_fingers')
# Keep the longer animation within the same range of poses as the short fixture.
benchmark_source=benchmark_source.replace('f*.025',f'f*{.2/benchmark_frames}').replace('f*.009',f'f*{.072/benchmark_frames}').replace('f*.014',f'f*{.112/benchmark_frames}')
if os.environ.get('SUB_BENCH_PROFILE')=='1':
    benchmark_source=benchmark_source.replace('started=time.perf_counter()', 'benchmark_profile=cProfile.Profile()\nbenchmark_profile.enable()\nstarted=time.perf_counter()')
    benchmark_source=benchmark_source.replace('elapsed=time.perf_counter()-started', 'elapsed=time.perf_counter()-started\nbenchmark_profile.disable()\npstats.Stats(benchmark_profile).strip_dirs().sort_stats("cumtime").print_stats(25)')
exec(compile(benchmark_source,str(benchmark_fixture),'exec'))
print('COMPONENT BENCHMARK FRAMES',benchmark_frames,'NATIVE',os.environ.get('SUB_NATIVE_COMPONENTS','1'))
