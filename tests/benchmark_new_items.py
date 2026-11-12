"""Real recognition of replayed reveals; source pictures stay on this computer.

The hatch is synthetic. The item pixels, catalog, OCR and live validation are real.
This measures capture-snapshot -> validated new detection, not capture FPS.
"""
import json
import re
import threading
import time
from pathlib import Path
import cv2
import numpy as np
from PIL import Image,ImageDraw
from itemsniper.library import VisualLibrary
from itemsniper.live import FrameTracker
from itemsniper.reveal import RevealLane
from itemsniper.vision import overlap,Vision


class Replay:
    def __init__(self):
        self.frame=None;self.tracker=FrameTracker();self.results=[];self.lock=threading.RLock()
    def snapshot(self):return self.frame
    def install(self,image,hits):
        with self.lock:
            if self.frame is None:return
            self.tracker.install(image,self.frame['image'],hits)
            self.results.extend((time.perf_counter(),hit) for hit in self.tracker.update(self.frame['image']))


def main():
    root=Path.cwd();directory=root/'data';catalog=json.loads((directory/'catalog.json').read_text(encoding='utf8'))
    library=VisualLibrary(directory);live=Replay();stats=[]
    lane=RevealLane(live,library,lambda:catalog,lambda:True,stats.append)
    deadline=time.monotonic()+30
    while not lane.ready and lane.error is None and time.monotonic()<deadline:time.sleep(.01)
    assert lane.ready,lane.error
    folder=Path.home()/'AppData/Local/Temp'
    toolbox=folder/'codex-clipboard-43f7520d-0d8d-47cb-946d-9efdf20b29fe.png'
    cases=folder/'codex-clipboard-98d4b62c-f056-441a-854a-902a3146f74b.png'
    specs=[(toolbox,'Bolts',(1262,79,64,64)),(toolbox,'Poxeram',(1326,79,64,64)),
        (toolbox,'Silicone tube',(1390,79,64,64)),(toolbox,'Sb.3 5-shot',(788,167,67,65)),
        (toolbox,'Sb.3 5-shot',(858,167,67,65)),(cases,'Bundle of wires',(196,63,64,64)),
        (cases,'Shustrilo',(1530,63,192,64)),(cases,'Fleece',(196,505,64,128))]
    rows=[];sequence=0
    for path,name,box in specs:
        visible=Image.open(path).convert('RGB');hidden=visible.copy();draw=ImageDraw.Draw(hidden);x,y,w,h=box
        draw.rectangle((x,y,x+w-1,y+h-1),fill='#202020')
        for offset in range(-h,w,12):draw.line((x+max(0,offset),y+max(0,-offset),x+min(w,offset+h),y+min(h,w-offset)),fill='#292929',width=4)
        # Establish an already open, unchanged inventory. No detection/cache of
        # the tested item is supplied to the worker.
        live.frame=None;time.sleep(.04)
        lane.detector.previous=cv2.cvtColor(np.asarray(hidden),cv2.COLOR_RGB2GRAY)
        lane.detector.queue.clear();live.tracker=FrameTracker();live.results=[]
        sequence+=1;live.frame={'image':hidden,'sequence':sequence,'at':time.time()}
        time.sleep(.04)
        assert not any(re.search(name,hit['name'],re.I) and overlap(box,hit['box'])>.6 for _,hit in live.results),'Hidden slot must not produce a detection'
        start=time.perf_counter();sequence+=1;live.frame={'image':visible,'sequence':sequence,'at':time.time()}
        deadline=start+3;found=[]
        while time.perf_counter()<deadline:
            found=[(at,hit) for at,hit in live.results if re.search(name,hit['name'],re.I) and overlap(box,hit['box'])>.6]
            if found or lane.error:break
            time.sleep(.002)
        row={'item':name,'box':box,'detected':bool(found),'snapshot_to_validated_hit_ms':round((found[0][0]-start)*1000,1) if found else None,
            'rotation':found[0][1].get('rotation') if found else None,'error':lane.error}
        rows.append(row);print(row,flush=True)
    live.frame=None;lane.close();lane.thread.join(5)
    (directory/'new-item-pipeline-benchmark.json').write_text(json.dumps({'mode':'local replay, warm models, synthetic hidden hatch; actual new item pixels; no cached identity',
        'cases':rows},ensure_ascii=False,indent=2),encoding='utf8')
    assert all(r['detected'] for r in rows)


if __name__=='__main__':main()
