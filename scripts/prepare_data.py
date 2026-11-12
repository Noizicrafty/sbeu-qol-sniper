"""Initialize a clean checkout from public reference snapshots, without player data."""
import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--download-images',action='store_true',help='Download public slot artwork and build the recognition index')
    args=parser.parse_args()
    directory=ROOT/'data';directory.mkdir(parents=True,exist_ok=True)
    for name in ('catalog.json','progression.json'):
        target=directory/name
        if not target.exists():shutil.copy2(ROOT/'reference'/name,target)
    if args.download_images:
        from itemsniper.library import VisualLibrary
        from itemsniper.core import save_json
        catalog=json.loads((directory/'catalog.json').read_text(encoding='utf8'))
        library=VisualLibrary(directory);last=[-1]
        def progress(status):
            done=status['ready']+status['failed']
            if done//250!=last[0]:last[0]=done//250;print(f"Images: {done}/{status['total']}, failed: {status['failed']}",flush=True)
        catalog['grid_templates']=library.prepare(catalog,progress)
        save_json(directory/'catalog.json',catalog)
        if library.status['failed']:raise SystemExit('Some images failed to download. Repeat the same command before building.')
        from itemsniper.vision import Vision
        from PIL import Image
        print('Preparing RU/EN OCR models for the offline EXE...',flush=True)
        vision=Vision();vision.prepare_caption_ocr();vision.text(Image.new('RGB',(320,240)))
    print('Public references ready. Existing local settings and progress were preserved.')


if __name__=='__main__':main()
