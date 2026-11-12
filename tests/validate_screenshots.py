"""Manual ground truth, real OCR and the complete index. Never uploads screenshots."""
import hashlib
import json
import re
import time
from pathlib import Path

import numpy as np
from PIL import Image,ImageDraw

from itemsniper.library import VisualLibrary
from itemsniper.vision import Vision,overlap


def measure(expected,hits,origin):
    unused=set(range(len(hits)));matched=[];missed=[];wrong=[]
    for truth in expected:
        box=truth['box'];local=(box[0]-origin[0],box[1]-origin[1],box[2],box[3])
        def iou(a,b):
            x,y,w,h=a;X,Y,W,H=b
            intersection=max(0,min(x+w,X+W)-max(x,X))*max(0,min(y+h,Y+H)-max(y,Y))
            return intersection/max(1,w*h+W*H-intersection)
        near=[i for i in unused if iou(local,hits[i]['box'])>=.5]
        correct=[i for i in near if re.search(truth['name'],hits[i]['name'],re.I)]
        if correct:
            i=max(correct,key=lambda i:hits[i]['score']);unused.remove(i)
            matched.append({'expected':truth,'hit':hits[i]})
        elif near:
            i=max(near,key=lambda i:hits[i]['score']);unused.remove(i)
            wrong.append({'expected':truth,'hit':hits[i]})
        else:missed.append(truth)
    return {'expected':len(expected),'matched':len(matched),'missed':missed,'wrong':wrong,
        'extra':[hits[i] for i in sorted(unused)],'matches':matched,
        'ambiguous':sum(m['hit'].get('ambiguous',False) for m in matched),
        'rotated_expected':sum(t.get('rotated',False) for t in expected),
        'rotated_matched':sum(m['expected'].get('rotated',False) for m in matched)}


def main():
    directory=Path('data');out=directory/'frame-validation'/'all-seven';out.mkdir(parents=True,exist_ok=True)
    truth=json.loads(Path('tests/fixtures/screenshot_truth.json').read_text(encoding='utf8'))
    catalog=json.loads((directory/'catalog.json').read_text(encoding='utf8'))
    library=VisualLibrary(directory);fast=Vision();fast.library=library;fast.prepare_caption_ocr()
    slow=Vision();slow.library=library;rows=[]
    for stamp,sides in truth['frames'].items():
        path=next((Path.home()/'Pictures/Screenshots').glob(f'*2026-11-11 {stamp}.png'))
        source=Image.open(path).convert('RGB');preview=source.copy();draw=ImageDraw.Draw(preview)
        for kind,region in [('inventory',(0,48,1224,949)),('loot',(1226,48,1919,949))]:
            image=source.crop(region);start=time.perf_counter()
            quick=fast.items(image,catalog,fast=True);quick_seconds=time.perf_counter()-start
            start=time.perf_counter();refined=slow.items(image,catalog);slow_seconds=time.perf_counter()-start
            merged=list(quick)
            for hit in refined:
                if not any(overlap(hit['box'],old['box'])>.4 for old in merged):merged.append(hit)
            analysis=dict(slow.last_analysis)
            row={'stamp':stamp,'kind':kind,'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
                'quick_ms':round(quick_seconds*1000),'refinement_ms':round(slow_seconds*1000),
                'fast':measure(sides[kind],quick,region),'refined':measure(sides[kind],merged,region),
                'analysis':analysis,'hits':merged}
            rows.append(row)
            for obj in sides[kind]:
                x,y,w,h=obj['box'];color='#38da6d' if any(m['expected']==obj for m in row['refined']['matches']) else '#ff4444'
                draw.rectangle((x,y,x+w,y+h),outline=color,width=2)
            for hit in merged:
                x,y,w,h=hit['box'];x+=region[0];y+=region[1]
                draw.text((x+2,y+15),hit['name'][:22],fill='#ffee66',stroke_width=1,stroke_fill='#000000')
            print(stamp,kind,'quick',row['fast']['matched'],'refined',row['refined']['matched'],'/',len(sides[kind]),'ms',row['quick_ms'],row['refinement_ms'],flush=True)
            (out/'results.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf8')
        preview.save(out/f'{stamp}.jpg',quality=90)
    print('Total',sum(r['refined']['matched'] for r in rows),'/',sum(r['refined']['expected'] for r in rows),flush=True)


if __name__=='__main__':main()
