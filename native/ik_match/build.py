"""Build, test and stage the Windows IK library and dependency notices."""
from pathlib import Path
import json
import platform
import shutil
import subprocess

crate = Path(__file__).resolve().parent
if platform.system() != 'Windows' or platform.machine().lower() not in {'amd64','x86_64'}:
    raise SystemExit('The addon currently enables native IK only on Windows x64.')
manifest = str(crate/'Cargo.toml')
for command in ('test','build'):
    subprocess.run(['cargo',command,'--release','--locked','--offline','--manifest-path',manifest],check=True)
target = crate.parent/'bin/sub_ik_match_native.dll'
target.parent.mkdir(parents=True,exist_ok=True)
shutil.copy2(crate/'target/release/sub_ik_match_native.dll',target)
metadata = json.loads(subprocess.check_output(['cargo','metadata','--format-version','1','--locked','--offline','--manifest-path',manifest]))
for package in metadata['packages']:
    if package['name'] == 'sub_ik_match_probe':
        continue
    source = Path(package['manifest_path']).parent
    destination = crate/'LICENSES/dependencies'/f'{package["name"]}-{package["version"]}'
    for file in source.iterdir():
        if file.is_file() and file.name.upper().startswith(('LICENSE','COPYING','COPYRIGHT')):
            destination.mkdir(parents=True,exist_ok=True)
            shutil.copy2(file,destination/file.name)
print(f'Staged {target}')
