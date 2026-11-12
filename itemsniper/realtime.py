"""Nonblocking image recognition, with independently scheduled OCR refinement."""
from __future__ import annotations

import copy
import threading
import time

import numpy as np

from .vision import Vision, overlap


class RealtimeVision:
    def __init__(self, library):
        self.fast=Vision();self.fast.library=library
        self.narrow=Vision();self.narrow.library=library
        self.slow=Vision();self.slow.library=library
        self.last_analysis={}
        self.urgent=lambda:False
        self.lock=threading.RLock()
        self.pending={};self.refined={};self.submitted={}
        self.full_pending={};self.full_refined={}
        self.wake=threading.Event();self.stop=threading.Event()
        self.thread=threading.Thread(target=self._worker,daemon=True)
        self.thread.start()
        self.full_thread=threading.Thread(target=self._full_worker,daemon=True)
        self.full_thread.start()

    def _worker(self):
        try:
            self.narrow.prepare_caption_ocr()
        except Exception as exc:
            self.error=str(exc)
        while not self.stop.is_set():
            self.wake.wait(.2);self.wake.clear()
            if self.urgent():continue
            with self.lock:
                if not self.pending:continue
                key=next(iter(self.pending));job=self.pending.pop(key)
            image,catalog,threshold,cell=job
            try:
                hits=self.narrow.scan(image,catalog,threshold,cell,view_key=key,fast=True)
                with self.lock:
                    self.refined[key]=(np.asarray(image).copy(),hits,id(catalog),threshold,cell)
                    self.full_pending[key]=job
                self.error=None
            except Exception as exc:
                self.error=str(exc)
            if self.pending:self.wake.set()

    def _full_worker(self):
        while not self.stop.wait(.1):
            if self.urgent():continue
            with self.lock:
                if not self.full_pending:continue
                key=next(iter(self.full_pending));job=self.full_pending.pop(key)
            image,catalog,threshold,cell=job
            try:
                hits=self.slow.items(image,catalog,threshold,cell)
                with self.lock:
                    self.full_refined[key]=(np.asarray(image).copy(),hits,id(catalog),threshold,cell)
            except Exception as exc:self.error=str(exc)

    def scan(self,image,catalog,threshold=.88,slot_size=64,view_key='loot'):
        if getattr(self,'urgent',lambda:False)():
            hits=[];self.last_analysis={'deferred_for_new_items':True}
        else:
            hits=self.fast.scan(image,catalog,threshold,slot_size,view_key,fast=True)
            self.last_analysis=copy.deepcopy(self.fast.last_analysis)
        array=np.asarray(image)
        now=time.monotonic()
        with self.lock:
            previous=self.submitted.get(view_key)
            changed=previous is None or previous[0].shape!=array.shape or not np.array_equal(previous[0],array)
            if changed and (previous is None or now-previous[1]>=.15):
                self.pending[view_key]=(image.copy(),catalog,threshold,slot_size)
                self.submitted[view_key]=(array.copy(),now)
                self.wake.set()
            refinements=[self.refined.get(view_key),self.full_refined.get(view_key)]
        for refined in refinements:
            if not refined or refined[0].shape!=array.shape or refined[2:]!=(id(catalog),threshold,slot_size):continue
            for candidate in refined[1]:
                x,y,w,h=map(int,candidate['box'])
                before=refined[0][y:y+h,x:x+w];current=array[y:y+h,x:x+w]
                # Do not resurrect a previously visible item after a move or scene change.
                if not current.size or before.shape!=current.shape or np.mean(np.abs(before.astype(np.int16)-current))>1.5:
                    continue
                near=next((hit for hit in hits if overlap(hit['box'],candidate['box'])>.4),None)
                if near is None:
                    hits.append(copy.deepcopy(candidate))
                elif near['name']==candidate['name']:
                    near.update({k:v for k,v in candidate.items() if k in ('count','count_score','fir','fir_score')})
        self.last_analysis['ocr_pending']=bool(self.pending)
        return hits

    def close(self):
        self.stop.set();self.wake.set()
