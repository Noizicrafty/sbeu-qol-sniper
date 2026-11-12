"""Replay a hidden-to-visible slot transition derived from supplied screenshots."""
import json
import re
import time
from pathlib import Path

from PIL import Image,ImageDraw

from itemsniper.library import VisualLibrary
from itemsniper.vision import Vision,overlap


def main(runtime=False):
    catalog=json.loads(Path('data/catalog.json').read_text(encoding='utf8'))
    if runtime:
        from itemsniper.realtime import RealtimeVision
        vision=RealtimeVision(VisualLibrary(Path('data')))
        deadline=time.monotonic()+30
        while not vision.narrow.caption_ready and time.monotonic()<deadline:time.sleep(.05)
    else:
        vision=Vision();vision.library=VisualLibrary(Path('data'));vision.prepare_caption_ocr()
    def scan(image,key):return vision.scan(image,catalog,view_key=key,**({} if runtime else {'fast':True}))
    cases=[('223437','Shustrilo',(1265,79,64,190),'loot'),
        ('223447','Slickers',(1391,142,64,64),'loot'),
        ('224657','Aramid',(1001,103,65,128),'inventory'),
        ('224755','Project documentation',(788,656,128,64),'inventory'),
        ('224755','MRE',(916,656,128,64),'inventory')]
    rows=[]
    for stamp,name,box,kind in cases:
        source=Image.open(next((Path.home()/'Pictures/Screenshots').glob(f'*2026-11-11 {stamp}.png'))).convert('RGB')
        region=(1226,48,1919,949) if kind=='loot' else (620,48,1224,949)
        visible=source.crop(region);x,y,w,h=box;local=(x-region[0],y-region[1],w,h)
        hidden=visible.copy();draw=ImageDraw.Draw(hidden);x,y,w,h=local
        draw.rectangle((x,y,x+w,y+h),fill='#202020')
        for offset in range(-h,w,12):draw.line((x+max(0,offset),y+max(0,-offset),x+min(w,offset+h),y+min(h,w-offset)),fill='#292929',width=4)
        key=stamp+name
        before=scan(hidden,key)
        if runtime:
            deadline=time.monotonic()+10
            while key not in vision.refined and time.monotonic()<deadline:scan(hidden,key);time.sleep(.05)
        start=time.perf_counter();after=scan(visible,key)
        if runtime:
            while not any(re.search(name,hit['name'],re.I) and overlap(hit['box'],local)>.6 for hit in after) and time.perf_counter()-start<5:
                time.sleep(.05);after=scan(visible,key)
        elapsed=time.perf_counter()-start
        start=time.perf_counter();scan(visible,key);idle=time.perf_counter()-start
        rows.append({'frame':stamp,'item':name,'region':local,'replay':'synthetic hatch masking of an actual visible slot',
            'hidden_false_hits':[hit for hit in before if overlap(hit['box'],local)>.6],
            'detected':any(re.search(name,hit['name'],re.I) and overlap(hit['box'],local)>.6 for hit in after),
            'reveal_ms':round(elapsed*1000,1),'unchanged_ms':round(idle*1000,1),'incremental':vision.last_analysis.get('incremental',False)})
        print(rows[-1],flush=True)
    Path('data/frame-validation/'+('realtime-reveal-benchmark.json' if runtime else 'reveal-benchmark.json')).write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf8')
    if runtime:vision.close()


if __name__=='__main__':
    import sys
    main('--runtime' in sys.argv)
