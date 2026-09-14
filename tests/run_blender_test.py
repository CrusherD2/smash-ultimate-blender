"""Launch a Blender test with user paths isolated before Blender starts.

python tests/run_blender_test.py --blender /path/to/blender tests/test_motion_list_blender.py
"""
import argparse
import os
from pathlib import Path
import subprocess
import sys
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--blender', required=True)
    parser.add_argument('test', type=Path)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='sub_blender_profile_') as folder:
        environment = os.environ.copy()
        environment['BLENDER_USER_RESOURCES'] = folder
        for name in ('CONFIG', 'SCRIPTS', 'EXTENSIONS', 'DATAFILES'):
            path = Path(folder)/name.lower()
            path.mkdir()
            environment['BLENDER_USER_' + name] = str(path)
        result = subprocess.run([
            args.blender, '--background', '--factory-startup', '--python-exit-code', '1',
            '--python', str(args.test.resolve()),
        ], env=environment, capture_output=True, text=True, encoding='utf-8', errors='replace',
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        print(result.stdout, end='')
        print(result.stderr, end='', file=sys.stderr)
        return result.returncode


if __name__ == '__main__':
    raise SystemExit(main())
