"""Build a Windows distribution containing all offline reference data and OCR models."""
from pathlib import Path
import json
import shutil
import subprocess
import sys
import numpy as np

root=Path(__file__).resolve().parent;data=root/'data';seed=root/'build'/'seed';seed.mkdir(parents=True,exist_ok=True)
catalog=json.loads((data/'catalog.json').read_text(encoding='utf8'))
catalog.pop('fir_template',None)
for key in ('grid_templates','icons','images'):
    if key in catalog:catalog[key]={name:'library/'+Path(path).name for name,path in catalog[key].items()}
(seed/'catalog.json').write_text(json.dumps(catalog,ensure_ascii=False),encoding='utf8')
shutil.copy2(data/'progression.json',seed/'progression.json')
with np.load(data/'visual-index.npz',allow_pickle=False) as archive:
    paths=archive['paths'].tolist();portable=[]
    for path in paths:
        source=Path(path)
        if not source.is_file():source=next((data/folder/source.name for folder in ('library','grids') if (data/folder/source.name).is_file()),source)
        relative=Path('library')/source.name;target=seed/relative;target.parent.mkdir(parents=True,exist_ok=True)
        if not target.exists():shutil.copy2(source,target)
        portable.append(str(relative))
    np.savez_compressed(seed/'visual-index.npz',names=archive['names'],paths=np.asarray(portable),dimensions=archive['dimensions'],vectors=archive['vectors'])
command=[sys.executable,'-m','PyInstaller','--noconfirm','--windowed','--onedir','--name','SBEU qol sniper',
    '--add-data',f'{root/"itemsniper"/"web"};itemsniper/web','--add-data',f'{root/"itemsniper"/"assets"};itemsniper/assets',
    '--add-data',f'{seed};seed','--collect-all','rapidocr','--collect-all','onnxruntime',
    '--hidden-import','mss.windows','--collect-all','dxcam','--collect-submodules','comtypes',
    '--exclude-module','matplotlib','--exclude-module','pytest',str(root/'launcher.py')]
subprocess.run(command,cwd=root,check=True)
print(root/'dist'/'SBEU qol sniper'/'SBEU qol sniper.exe')
