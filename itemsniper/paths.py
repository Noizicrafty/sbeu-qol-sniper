import os
import shutil
import sys
from pathlib import Path

def data_directory():
    if '--data-dir' in sys.argv:
        return Path(sys.argv[sys.argv.index('--data-dir')+1]).resolve()
    if not getattr(sys,'frozen',False):return Path(__file__).resolve().parent.parent/'data'
    # A development build next to this checkout keeps the user's existing profile.
    for checkout in (Path(sys.executable).resolve().parent.parent,Path(sys.executable).resolve().parent.parent.parent):
        if (checkout/'itemsniper'/'app.py').is_file() and (checkout/'data'/'catalog.json').is_file():return checkout/'data'
    return Path(os.environ.get('LOCALAPPDATA',Path.home()))/'SBEU qol sniper'

def bootstrap(directory):
    directory.mkdir(parents=True,exist_ok=True)
    if not getattr(sys,'frozen',False):return
    seed=Path(sys._MEIPASS)/'seed'
    if not seed.is_dir():return
    for source in seed.rglob('*'):
        if source.is_file():
            target=directory/source.relative_to(seed)
            if not target.exists():target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,target)
