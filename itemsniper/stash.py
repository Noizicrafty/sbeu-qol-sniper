"""Deduplicate visible stash objects while the user scrolls manually."""
from __future__ import annotations
import copy
import time
import cv2
import numpy as np


class StashCollector:
    def __init__(self):self.reset()
    def reset(self):
        self.active=False;self.tracks={};self.offset=0.;self.previous=None;self.frames=0;self.warning='';self.at=None
    def start(self):self.reset();self.active=True;self.at=time.time()
    def observe(self,image,hits,cell=64,allow_edges=False):
        if not self.active:return
        gray=cv2.cvtColor(np.asarray(image),cv2.COLOR_RGB2GRAY)
        if self.previous is not None and self.previous.shape==gray.shape:
            difference=float(np.mean(cv2.absdiff(gray,self.previous)))
            if difference>6:
                orb=cv2.ORB_create(nfeatures=1200,edgeThreshold=10)
                ka,da=orb.detectAndCompute(self.previous,None);kb,db=orb.detectAndCompute(gray,None)
                shifts=[]
                if da is not None and db is not None and len(db)>2:
                    for pair in cv2.BFMatcher(cv2.NORM_HAMMING).knnMatch(da,db,k=2):
                        if len(pair)!=2:continue
                        a,b=pair
                        if a.distance<b.distance*.7:
                            x,y=ka[a.queryIdx].pt;X,Y=kb[a.trainIdx].pt
                            if abs(x-X)<cell*.12:shifts.append(y-Y)
                if len(shifts)<6:
                    self.warning='Не удалось совместить кадры. Прокручивайте схрон плавнее; этот кадр не добавлен.'
                    return
                median=float(np.median(shifts));agree=[d for d in shifts if abs(d-median)<4]
                if len(agree)<6 or len(agree)<len(shifts)*.55:
                    self.warning='Неоднозначная прокрутка: кадр не добавлен, чтобы не удвоить вещи.';return
                self.offset+=median
        elif self.previous is not None:
            self.warning='Размер окна изменился. Завершите текущий скан и начните новый.';return
        self.previous=gray;self.frames+=1;self.warning=''
        for hit in hits:
            if hit.get('ambiguous'):continue
            x,y,w,h=hit['box']
            if not allow_edges and (y<3 or y+h>gray.shape[0]-3):continue
            key=(round(x/(cell*.45)),round((y+self.offset)/(cell*.45)))
            # A refined result replaces its earlier observation rather than adding again.
            self.tracks[key]=copy.deepcopy(hit)
        self.at=time.time()
    def items(self):
        result={}
        for h in self.tracks.values():
            v=result.setdefault(h['name'],{'count':0,'fir':0,'unknown':0})
            n=h.get('count',1);v['count']+=n;v['fir']+=n if h.get('fir')=='yes' else 0;v['unknown']+=n if h.get('fir')=='unknown' else 0
        return result
    def finish(self):self.active=False;return {'items':self.items(),'at':self.at,'scope':'stash','warning':self.warning or 'Проверьте видимые предметы. Закрытые контейнеры не считываются.'}
    def snapshot(self):return {'active':self.active,'frames':self.frames,'items':len(self.tracks),'warning':self.warning,'at':self.at}


class StashSession:
    """Separate coordinate systems for the main stash and each visible case."""
    def __init__(self):self.reset()
    def reset(self):
        self.active=False;self.views={};self.at=None;self.warning='';self.window_size=None;self.visible_containers=0
    def start(self):self.reset();self.active=True;self.at=time.time()
    def begin_frame(self,size,containers=0):
        self.visible_containers=containers
        if not self.active:return False
        if self.window_size is not None and self.window_size!=size:
            self.warning='Размер окна изменился во время сбора. Завершите скан и начните новый.';return False
        self.window_size=size;return True
    def observe_view(self,key,image,hits,cell=64):
        if not self.active:return
        if key not in self.views:self.views[key]=StashCollector();self.views[key].start()
        self.views[key].observe(image,hits,cell,allow_edges=key.startswith('container:'));self.at=time.time()
    def observe(self,image,hits,cell=64):self.observe_view('stash',image,hits,cell)
    def items(self):
        result={}
        for view in self.views.values():
            for name,value in view.items().items():
                entry=result.setdefault(name,{'count':0,'fir':0,'unknown':0})
                for field in entry:entry[field]+=value[field]
        return result
    def finish(self):
        self.active=False
        return {'items':self.items(),'at':self.at,'scope':'stash','warning':self.snapshot()['warning'] or 'Проверьте схрон и открытые ящики. Закрытые и перекрытые предметы не угадываются.'}
    def snapshot(self):
        warnings=[v.warning for v in self.views.values() if v.warning]
        if self.visible_containers:warnings.append('Основной схрон перекрыт окнами. Закройте их, чтобы собрать оставшуюся часть схрона.')
        return {'active':self.active,'frames':sum(v.frames for v in self.views.values()),'items':sum(len(v.tracks) for v in self.views.values()),
            'warning':self.warning or ' '.join(warnings),'at':self.at,'views':len(self.views),'containers':self.visible_containers}
