"""Visible floating inventory windows. Identity is inferred from pixels, never game IDs."""
from __future__ import annotations
import math
import time
import cv2
import numpy as np
from PIL import Image


def intersection(a,b):
    x,y,w,h=a;X,Y,W,H=b
    left,top=max(x,X),max(y,Y);right,bottom=min(x+w,X+W),min(y+h,Y+H)
    return (left,top,max(0,right-left),max(0,bottom-top))


def detect_containers(image):
    array=np.asarray(image);height,width=array.shape[:2];expected=64*height/1080
    rgb=array.astype(np.float32);r,g,b=rgb[:,:,0],rgb[:,:,1],rgb[:,:,2]
    red=((r>50)&(r>g*1.4)&(r>b*1.3)).astype(np.uint8)*255
    _,_,components,_=cv2.connectedComponentsWithStats(red)
    buttons=[(int(x),int(y),int(w),int(h)) for x,y,w,h,area in components[1:]
        if expected*.22<w<expected*.75 and expected*.13<h<expected*.5 and 1.3<w/h<2.1 and area/(w*h)>.72]
    if not buttons:return []
    gray=cv2.cvtColor(array,cv2.COLOR_RGB2GRAY)
    lines=cv2.HoughLinesP(cv2.Canny(gray,50,130),1,np.pi/180,max(30,round(expected)),minLineLength=round(expected*2),maxLineGap=8)
    if lines is None:return []
    horizontal=[tuple(map(int,line)) for line in lines[:,0] if abs(int(line[1])-int(line[3]))<3]
    vertical=[tuple(map(int,line)) for line in lines[:,0] if abs(int(line[0])-int(line[2]))<3]
    panels=[]
    for bx,by,bw,bh in buttons:
        right=bx+bw+4
        tops=[line for line in horizontal if by-12<line[1]<by+2 and abs(max(line[0],line[2])-right)<14 and abs(line[2]-line[0])>expected*2]
        if not tops:continue
        line=max(tops,key=lambda line:abs(line[2]-line[0]))
        left=max(0,min(line[0],line[2]));top=line[1]
        bottoms=[line for line in horizontal if line[1]>by+expected*2 and abs(min(line[0],line[2])-left)<14 and abs(max(line[0],line[2])-right)<14]
        if not bottoms:continue
        bottom=max(line[1] for line in bottoms)
        if bottom>height*.97:continue
        borders=[line for line in horizontal if by+bh-2<=line[1]<=by+bh+10 and min(line[0],line[2])<=left+14 and max(line[0],line[2])>=right-14]
        content_top=max(line[1] for line in borders)+3 if borders else by+bh+7
        bounds=(left,top,min(width,right)-left,bottom-top+1)
        content=(left+4,content_top,min(width,right)-left-8,bottom-content_top-3)
        x,y,w,h=content
        # Inspect windows have no repeated cell lattice; they must never be scanned as slots.
        xs=sorted({a for a,c,A,C in vertical if x-6<=a<=x+w+6 and min(c,C)<y+h and max(c,C)>y})
        ys=sorted({c for a,c,A,C in horizontal if y-6<=c<=y+h+6 and min(a,A)<x+w and max(a,A)>x})
        def gaps(values):return [b-a for i,a in enumerate(values) for b in values[i+1:] if expected*.55<b-a<expected*1.4]
        distances=gaps(xs)+gaps(ys)
        if len(distances)<6:continue
        histogram=np.bincount(np.asarray(distances,dtype=int));peak=int(np.convolve(histogram,np.ones(3),mode='same').argmax())
        if sum(abs(d-peak)<=2 for d in gaps(xs))<2 or sum(abs(d-peak)<=2 for d in gaps(ys))<2:continue
        cell=expected if abs(peak-expected)<=2 else peak
        edge=array[max(0,top-1):top+3,left:min(width,right)]
        focus=float(np.mean((edge[:,:,0]>115)&(edge[:,:,1]>95)&(edge[:,:,2]<100))) if edge.size else 0
        panel={'bounds':bounds,'content':content,'cell':round(cell),'focus':focus}
        if not any(intersection(bounds,old['bounds'])[2]*intersection(bounds,old['bounds'])[3]>min(bounds[2]*bounds[3],old['bounds'][2]*old['bounds'][3])*.8 for old in panels):panels.append(panel)
    return sorted(panels,key=lambda p:(p['bounds'][0],p['bounds'][1]))


def visible_contents(image,panels):
    """Mask obscured parts. Unknown stacking order excludes the overlap from both views."""
    result=[]
    for panel in panels:
        x,y,w,h=panel['content'];crop=np.asarray(image.crop((x,y,x+w,y+h))).copy();occluded=[]
        for other in panels:
            if other is panel:continue
            if panel['focus']>other['focus']+.05:continue
            X,Y,W,H=intersection(panel['content'],other['bounds'])
            if W>0 and H>0:
                crop[Y-y:Y-y+H,X-x:X-x+W]=0;occluded.append((X-x,Y-y,W,H))
        logical=(max(1,round(w/panel['cell']))*64,max(1,round(h/panel['cell']))*64)
        normalized=Image.fromarray(crop).resize(logical,Image.Resampling.BILINEAR)
        occluded=[(round(X*logical[0]/w),round(Y*logical[1]/h),round(W*logical[0]/w),round(H*logical[1]/h)) for X,Y,W,H in occluded]
        result.append((panel,normalized,occluded))
    return result


class ContainerRegistry:
    def __init__(self):self.entries={};self.sequence=0
    def identify(self,views):
        active=set();result=[]
        for panel,image,occluded in views:
            gray=cv2.cvtColor(np.asarray(image),cv2.COLOR_RGB2GRAY)
            thumb=cv2.resize(gray,(64,64));orb=cv2.ORB_create(nfeatures=700,edgeThreshold=8)
            keypoints,features=orb.detectAndCompute(gray,None)
            best=None;best_score=0
            for key,entry in self.entries.items():
                if key in active or entry['shape']!=gray.shape:continue
                difference=float(np.mean(cv2.absdiff(entry['thumb'],thumb)))
                score=1-difference/5 if difference<1 else 0
                if score<.8 and features is not None and entry['features'] is not None:
                    pairs=cv2.BFMatcher(cv2.NORM_HAMMING).knnMatch(entry['features'],features,k=2)
                    shifts=[]
                    for pair in pairs:
                        if len(pair)!=2:continue
                        a,b=pair
                        if a.distance<b.distance*.65:
                            old=entry['points'][a.queryIdx];new=keypoints[a.trainIdx].pt
                            if abs(old[0]-new[0])<panel['cell']*.12:shifts.append(old[1]-new[1])
                    if len(shifts)>=8:
                        median=float(np.median(shifts));consistent=sum(abs(s-median)<4 for s in shifts)
                        ratio=consistent/max(1,min(len(entry['points']),len(keypoints)))
                        if ratio>.3:score=max(score,.7+min(.25,ratio/3))
                if score>best_score:best,best_score=key,score
            if best is None or best_score<.7:
                self.sequence+=1;best=f'container:{self.sequence}'
            active.add(best)
            self.entries[best]={'shape':gray.shape,'thumb':thumb,'features':features,'points':[p.pt for p in keypoints],'bounds':panel['bounds'],'at':time.time()}
            result.append((best,panel,image,occluded))
        return result
