"""Prioritize newly changed slots independently of whole-panel OCR/refinement."""
from __future__ import annotations
from collections import deque
import logging
import threading
import time
import cv2
import numpy as np
from PIL import Image
from .vision import Vision,overlap
from .slots import SlotGeometry
from .containers import detect_containers,visible_contents
from .gridfast import caption_anchors,read_grid_batch,grid_image_stream


def inventory_visible(image):
    """The selected Items navigation tab remains visible above floating cases."""
    w,h=image.size
    a=np.asarray(image.crop((round(w*.096),round(h*.014),round(w*.172),round(h*.032))))
    if not a.size:return False
    gray=cv2.cvtColor(a,cv2.COLOR_RGB2GRAY)
    return float(np.mean(gray>125))>.48


class RevealDetector:
    def __init__(self,library):
        self.art=Vision();self.art.library=library
        self.ocr=Vision();self.ocr.library=library
        self.previous=None;self.queue=deque();self.generation=None
    def prepare(self):
        self.ocr.prepare_caption_ocr()
        # Build alias dictionaries before the first revealed item, not on its path.
    def regions(self,image,cell=64):
        gray=cv2.cvtColor(np.asarray(image),cv2.COLOR_RGB2GRAY)
        initial=self.previous is None or self.previous.shape!=gray.shape
        if initial:mask=np.ones(gray.shape,dtype=np.uint8)*255;self.queue.clear()
        else:mask=(cv2.absdiff(gray,self.previous)>20).astype(np.uint8)*255
        self.previous=gray
        mask[:round(gray.shape[0]*.045)]=0;mask[round(gray.shape[0]*.88):]=0
        changed_pixels=np.count_nonzero(mask)
        if changed_pixels<24:return []
        opening=initial or changed_pixels>gray.size*.3
        mask=cv2.morphologyEx(mask,cv2.MORPH_CLOSE,np.ones((9,9),np.uint8))
        _,_,stats,_=cv2.connectedComponentsWithStats(mask)
        boxes=[];w,h=image.size
        for x,y,W,H,area in stats[1:]:
            if area<24:continue
            pad=round(cell*.7)
            if W*H>cell*cell*16:
                # Opening a menu/case must stream results tile by tile. A later
                # reveal jumps ahead of this initial sweep.
                stride=round(cell*2);side=round(cell*3)
                for Y in range(int(y),min(h,int(y+H)),stride):
                    for X in range(int(x),min(w,int(x+W)),stride):
                        boxes.append((max(0,X-pad),max(0,Y-pad),min(w,X+side),min(h,Y+side)))
            else:boxes.append((max(0,int(x)-pad),max(0,int(y)-pad),min(w,int(x+W)+pad),min(h,int(y+H)+pad)))
        # Prioritize new compact changes, then the loot panel and rig; never wait
        # for equipment OCR on the opposite side of the screen.
        if opening:
            boxes=[b for b in boxes if gray[b[1]:b[3]:2,b[0]:b[2]:2].std()>12 and np.count_nonzero(gray[b[1]:b[3]:2,b[0]:b[2]:2]>125)>16]
            boxes.sort(key=lambda b:(round(b[1]/cell),b[0]<w*.33,b[0]<w*.63,b[0]))
            # Read the common rig and loot opening immediately, ahead of the
            # surrounding equipment and empty grids. Generic tiles follow.
            boxes=[(max(0,round(w*.41-cell*.3)),max(0,round(h*.15-cell*.3)),min(w,round(w*.57)),min(h,round(h*.15+cell*2.2))),
                   (max(0,round(w*.655-cell*.2)),max(0,round(h*.073-cell*.2)),min(w,round(w*.8)),min(h,round(h*.073+cell*2.5)))]+boxes
        else:boxes.sort(key=lambda b:((b[2]-b[0])*(b[3]-b[1]),b[0]<w*.63,abs(b[1]-h*.15)))
        return boxes
    def enqueue(self,boxes,at):
        for box in reversed(boxes):
            x,y,X,Y=box
            self.queue=deque(job for job in self.queue if overlap((x,y,X-x,Y-y),(job[0][0],job[0][1],job[0][2]-job[0][0],job[0][3]-job[0][1]))<.8)
            self.queue.appendleft((box,at))
        while len(self.queue)>160:self.queue.pop()
    def recognize(self,image,box,catalog,cell,emit,defer=None):
        x,y,X,Y=box;crop=image.crop(box)
        def translate(hits):return [{**hit,'box':(hit['box'][0]+x,hit['box'][1]+y,*hit['box'][2:])} for hit in hits]
        geometry=SlotGeometry(crop,cell)
        pad=round(cell*.7);focus=(pad,pad,max(1,crop.width-pad*2),max(1,crop.height-pad*2))
        hits=self.art.items(crop,catalog,.88,cell,fast=True,geometry=geometry,focus=focus)
        if hits:emit(translate(hits),'image')
        # Image hits are already visible. Short-label recognition only refines
        # the remaining slots; no whole-frame text detector is involved.
        def caption():
            refined=self.ocr.items(crop,catalog,.88,cell,fast=True,geometry=geometry,seed_hits=hits,focus=focus)
            extra=[h for h in refined if not any(overlap(h['box'],old['box'])>.4 and h['name']==old['name'] for old in hits)]
            if extra:emit(translate(extra),'caption')
            return extra
        if defer is not None:defer(caption);return hits
        return hits+caption()


class RevealLane:
    def __init__(self,live,library,catalog,enabled,stats):
        self.live=live;self.catalog=catalog;self.enabled=enabled;self.stats=stats
        self.detector=RevealDetector(library);self.stop=threading.Event();self.ready=False;self.error=None
        self.caption_lock=threading.Lock();self.caption_jobs=[];self.caption_wake=threading.Event()
        self.grid_images=deque()
        self.thread=threading.Thread(target=self.run,daemon=True);self.thread.start()
    def run(self):
        try:
            self.detector.prepare()
            # Warm catalog aliases and inference kernels on a real-shaped blank
            # crop. It is not a captured/detected frame and never contributes FPS.
            blank=Image.new('RGB',(192,192));catalog=self.catalog()
            self.detector.art.items(blank,catalog,fast=True);self.detector.ocr.items(blank,catalog,fast=True)
            threading.Thread(target=self.caption_worker,daemon=True).start()
            self.ready=True;sequence=None
            while not self.stop.is_set():
                snapshot=self.live.snapshot()
                if not self.enabled() or snapshot is None:
                    self.detector.previous=None;self.detector.queue.clear()
                    self.grid_images.clear()
                    with self.caption_lock:self.caption_jobs.clear()
                    self.stop.wait(.02);continue
                image=snapshot['image'];cell=round(64*image.height/1080)
                if not inventory_visible(image):
                    self.detector.previous=None;self.detector.queue.clear()
                    self.grid_images.clear()
                    with self.caption_lock:self.caption_jobs.clear()
                    self.stop.wait(.02);continue
                if sequence!=snapshot['sequence']:
                    sequence=snapshot['sequence']
                    if self.detector.previous is None:
                        grid_work=[]
                        panels=detect_containers(image)
                        for panel_index,(panel,crop,occluded) in enumerate(visible_contents(image,panels)):
                            captions=caption_anchors(crop)
                            self.grid_images.append((grid_image_stream(self.detector.art,crop,captions),panel,crop,occluded,image,snapshot['at']))
                            for offset in range(0,len(captions),4):
                                def grid_job(crop=crop,panel=panel,captions=captions[offset:offset+4],image=image,occluded=occluded,seen_at=snapshot['at']):
                                    hits=read_grid_batch(self.detector.ocr,crop,captions,self.catalog())
                                    from .containers import intersection
                                    hits=[hit for hit in hits if not any(intersection(hit['box'],mask)[2]*intersection(hit['box'],mask)[3]>0 for mask in occluded)]
                                    x,y,w,h=panel['content'];sx,sy=w/crop.width,h/crop.height
                                    physical=[]
                                    for hit in hits:
                                        X,Y,W,H=hit['box'];physical.append({**hit,'box':(round(x+X*sx),round(y+Y*sy),round(W*sx),round(H*sy))})
                                    if physical:
                                        self.live.install(image,physical)
                                        self.stats({'new_item_ms':round((time.time()-seen_at)*1000,1),'method':'grid-caption','queue':len(self.detector.queue)})
                                grid_work.append((offset,panel_index,grid_job))
                        with self.caption_lock:
                            self.caption_jobs.extend((snapshot['at']+.000001,job) for _,_,job in sorted(grid_work,key=lambda j:j[:2]))
                        self.caption_wake.set()
                    boxes=self.detector.regions(image,cell)
                    self.detector.enqueue(boxes,snapshot['at'])
                if self.grid_images and (not self.detector.queue or self.detector.queue[0][1]<=self.grid_images[0][5]):
                    stream,panel,crop,occluded,source,seen_at=self.grid_images.popleft()
                    try:hits=next(stream)
                    except StopIteration:continue
                    self.grid_images.append((stream,panel,crop,occluded,source,seen_at))
                    from .containers import intersection
                    hits=[hit for hit in hits if not any(intersection(hit['box'],mask)[2]*intersection(hit['box'],mask)[3]>0 for mask in occluded)]
                    x,y,w,h=panel['content'];sx,sy=w/crop.width,h/crop.height
                    physical=[]
                    for hit in hits:
                        X,Y,W,H=hit['box'];physical.append({**hit,'box':(round(x+X*sx),round(y+Y*sy),round(W*sx),round(H*sy))})
                    if physical:
                        self.live.install(source,physical);self.stats({'new_item_ms':round((time.time()-seen_at)*1000,1),'method':'grid-image','queue':len(self.detector.queue)})
                    continue
                if not self.detector.queue:self.stop.wait(.003);continue
                box,seen_at=self.detector.queue.popleft();start=time.perf_counter()
                def emit(hits,method,image=image,seen_at=seen_at,start=start):
                    self.live.install(image,hits)
                    self.stats({'new_item_ms':round((time.time()-seen_at)*1000,1),'recognition_ms':round((time.perf_counter()-start)*1000,1),'method':method,'queue':len(self.detector.queue)})
                def defer(callback,seen_at=seen_at):
                    with self.caption_lock:
                        self.caption_jobs.append((seen_at,callback))
                        if len(self.caption_jobs)>80:self.caption_jobs.pop(0)
                    self.caption_wake.set()
                self.detector.recognize(image,box,self.catalog(),cell,emit,defer=defer)
        except Exception as exc:
            self.error=str(exc);logging.exception('New-slot recognition failed')
    def caption_worker(self):
        while not self.stop.is_set():
            self.caption_wake.wait(.05);self.caption_wake.clear()
            while not self.stop.is_set():
                with self.caption_lock:
                    if not self.caption_jobs:break
                    index=max(range(len(self.caption_jobs)),key=lambda i:self.caption_jobs[i][0])
                    _,callback=self.caption_jobs.pop(index)
                try:callback()
                except Exception as exc:self.error=str(exc);logging.exception('New-slot caption recognition failed')
    def close(self):self.stop.set();self.caption_wake.set()
