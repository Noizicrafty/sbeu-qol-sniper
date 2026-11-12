"""30 Hz screen sampling and pixel validation, independent of model inference."""
from __future__ import annotations
import copy
import threading
import time
from collections import deque
import cv2
import numpy as np
from PIL import Image


class FrameTracker:
    def __init__(self):self.tracks=[];self.shape=None
    @staticmethod
    def patch(gray,box):
        x,y,w,h=map(int,box);dx=max(2,round(w*.15));dy=max(3,round(min(w,h)*.25))
        crop=gray[max(0,y+dy):y+h-dy,max(0,x+dx):x+w-dx]
        return None if not crop.size else cv2.resize(crop,(24,24))
    @staticmethod
    def same(a,b):
        if a is None or b is None:return False
        # A replaced, removed or still hidden item invalidates its old annotation.
        return float(np.mean(cv2.absdiff(a,b)))<8 and float(cv2.matchTemplate(a,b,cv2.TM_CCOEFF_NORMED)[0,0])>.88
    def update(self,image):
        gray=cv2.cvtColor(np.asarray(image),cv2.COLOR_RGB2GRAY)
        if self.shape!=gray.shape:self.tracks=[];self.shape=gray.shape
        self.tracks=[t for t in self.tracks if self.same(t['patch'],self.patch(gray,t['hit']['box']))]
        return [dict(t['hit']) for t in self.tracks]
    def install(self,source,current,hits):
        if source.size!=current.size:return
        shape=(current.height,current.width)
        if self.shape!=shape:self.tracks=[];self.shape=shape
        from .vision import overlap
        def local_patch(image,box):
            x,y,w,h=map(int,box);dx=max(2,round(w*.15));dy=max(3,round(min(w,h)*.25))
            region=image.crop((max(0,x+dx),max(0,y+dy),min(image.width,x+w-dx),min(image.height,y+h-dy)))
            if not region.width or not region.height:return None
            return cv2.resize(cv2.cvtColor(np.asarray(region),cv2.COLOR_RGB2GRAY),(24,24))
        for hit in hits:
            patch=local_patch(source,hit['box'])
            if not self.same(patch,local_patch(current,hit['box'])):continue
            self.tracks=[t for t in self.tracks if overlap(t['hit']['box'],hit['box'])<.5]
            self.tracks.append({'hit':copy.deepcopy(hit),'patch':patch})


class LiveScreen:
    def __init__(self,window,enabled):
        self.window=window;self.enabled=enabled;self.lock=threading.RLock();self.stop=threading.Event()
        self.latest=None;self.output=None;self.sequence=0;self.tracker=FrameTracker();self.samples=deque(maxlen=90);self.error=None
        self.thread=threading.Thread(target=self.run,daemon=True);self.thread.start()
    def snapshot(self):
        with self.lock:return self.latest
    def clear(self):
        with self.lock:self.tracker.tracks=[];self.output=None
    def install(self,source,hits):
        with self.lock:
            if self.latest:
                self.tracker.install(source,self.latest['image'],hits)
                if self.output:self.output={**self.output,'hits':[dict(t['hit']) for t in self.tracker.tracks],'revision':self.output.get('revision',0)+1}
    def run(self):
        import mss
        deadline=time.perf_counter();camera=None
        try:
            with mss.mss() as screen:
                bounds=dict(screen.monitors[0])
                primary=dict(screen.monitors[1])
                try:
                    import dxcam
                    camera=dxcam.create(output_color='RGB')
                except Exception:camera=None
                while not self.stop.is_set():
                    w=self.window.current()
                    if not self.enabled() or not w.get('focused'):
                        with self.lock:self.latest=None;self.output=None;self.tracker.tracks=[];self.samples.clear()
                        self.stop.wait(.05);deadline=time.perf_counter();continue
                    start=time.perf_counter();region={k:w[k] for k in ('left','top','width','height')}
                    accelerated=camera is not None and primary['left']==primary['top']==0 and w['left']>=0 and w['top']>=0 and w['left']+w['width']<=primary['width'] and w['top']+w['height']<=primary['height']
                    if accelerated:
                        try:array=camera.grab(region=(w['left'],w['top'],w['left']+w['width'],w['top']+w['height']))
                        except Exception:
                            camera.release();camera=None;continue
                        if array is None:
                            deadline=max(deadline+1/30,time.perf_counter());self.stop.wait(max(0,deadline-time.perf_counter()));continue
                        image=Image.fromarray(array)
                    else:
                        shot=screen.grab(region);image=Image.frombytes('RGB',shot.size,shot.rgb)
                    with self.lock:
                        self.sequence+=1;self.latest={'image':image,'window':w,'sequence':self.sequence,'at':time.time()}
                        hits=self.tracker.update(image);self.samples.append(start)
                        fps=(len(self.samples)-1)/(self.samples[-1]-self.samples[0]) if len(self.samples)>1 else 0
                        self.output={'sequence':self.sequence,'hits':hits,'window':w,'bounds':bounds,'fps':round(fps,1),'backend':'DXGI' if accelerated else 'GDI','frame_ms':round((time.perf_counter()-start)*1000,1)}
                    deadline=max(deadline+1/30,time.perf_counter());self.stop.wait(max(0,deadline-time.perf_counter()))
        except Exception as exc:self.error=str(exc)
        finally:
            if camera is not None:camera.release()
    def close(self):self.stop.set()
