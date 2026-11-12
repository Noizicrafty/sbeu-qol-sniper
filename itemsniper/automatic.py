"""Window geometry and visible UI pixels only. No process handles or game files."""
from __future__ import annotations
import ctypes
from ctypes import wintypes
import json
import time
import re
from pathlib import Path
import cv2
import numpy as np
from .core import save_json


class TarkovWindow:
    def current(self):
        if not hasattr(ctypes,'windll'):return {'found':False,'focused':False}
        u=ctypes.windll.user32
        u.GetForegroundWindow.restype=wintypes.HWND
        u.GetClassNameW.argtypes=[wintypes.HWND,wintypes.LPWSTR,ctypes.c_int]
        u.GetWindowTextW.argtypes=[wintypes.HWND,wintypes.LPWSTR,ctypes.c_int]
        foreground=u.GetForegroundWindow();found=[]
        def visit(hwnd,_):
            title=ctypes.create_unicode_buffer(512);kind=ctypes.create_unicode_buffer(128)
            u.GetWindowTextW(hwnd,title,512);u.GetClassNameW(hwnd,kind,128)
            if kind.value=='UnityWndClass' and 'tarkov' in title.value.lower() and u.IsWindowVisible(hwnd):found.append(hwnd)
            return True
        callback=ctypes.WINFUNCTYPE(wintypes.BOOL,wintypes.HWND,wintypes.LPARAM)(visit)
        u.EnumWindows(callback,0)
        if not found:return {'found':False,'focused':False}
        hwnd=foreground if foreground in found else found[0]
        rect=wintypes.RECT();origin=wintypes.POINT(0,0)
        u.GetClientRect(hwnd,ctypes.byref(rect));u.ClientToScreen(hwnd,ctypes.byref(origin))
        width,height=rect.right,rect.bottom
        dpi=u.GetDpiForWindow(hwnd) if hasattr(u,'GetDpiForWindow') else 96
        return {'found':True,'focused':hwnd==foreground and not u.IsIconic(hwnd),
            'hwnd':hwnd,'left':origin.x,'top':origin.y,'width':width,'height':height,'dpi':dpi}


class AutoCalibration:
    def __init__(self,path):
        self.path=Path(path);self.entries={}
        if self.path.exists():
            try:self.entries=json.loads(self.path.read_text(encoding='utf8'))
            except (ValueError,OSError):pass
    def clear(self):
        self.entries={};self.path.unlink(missing_ok=True)
    def resolve(self,image,window,scene='inventory'):
        key=f"{window['width']}x{window['height']}@{window.get('dpi',96)}:{scene}"
        if key in self.entries and self.entries[key].get('version')==2:return self.entries[key]
        w,h=image.size;expected=64*h/1080
        gray=cv2.cvtColor(np.asarray(image),cv2.COLOR_RGB2GRAY)
        edges=cv2.Canny(gray,60,140)
        lines=cv2.HoughLinesP(edges,1,np.pi/180,threshold=max(20,round(expected*.6)),minLineLength=max(30,round(expected*.7)),maxLineGap=4)
        gaps=[]
        if lines is not None:
            for axis in (0,1):
                positions=sorted({int(line[axis]) for line in lines[:,0] if abs(int(line[axis])-int(line[axis+2]))<3})
                for i,x in enumerate(positions):
                    gaps.extend(X-x for X in positions[i+1:] if expected*.65<X-x<expected*1.4)
        cell=expected;confidence='resolution'
        if gaps:
            histogram=np.bincount(np.asarray(gaps,dtype=int));smoothed=np.convolve(histogram,np.ones(3),mode='same')
            peak=int(smoothed.argmax())
            if smoothed[peak]>=6:
                cell=float(peak);confidence='grid-lines'
                if abs(cell-expected)<=2:cell=expected
        result={'version':2,'width':w,'height':h,'dpi':window.get('dpi',96),'cell':round(max(24,min(160,cell)),2),
            'ui_scale':round(cell/64,4),'learned_at':time.time(),'method':confidence}
        separators=[] if lines is None else [(int(x),abs(int(Y)-int(y)),min(int(y),int(Y)),max(int(y),int(Y))) for x,y,X,Y in lines[:,0]
            if abs(int(X)-int(x))<4 and w*.48<x<w*.8 and abs(int(Y)-int(y))>h*.6]
        separator=max(separators,key=lambda p:(p[1],-abs(p[0]-w*.638))) if separators else None
        result['split_ratio']=separator[0]/w if separator else .638
        result['grid_top_ratio']=max(.035,min(.14,separator[2]/h)) if separator else .044
        result['grid_bottom_ratio']=max(.8,min(.97,separator[3]/h)) if separator else (.96 if scene=='stash' else .879)
        self.entries[key]=result;save_json(self.path,self.entries)
        return result


class SceneDetector:
    def __init__(self):self.previous=None;self.scene='unknown';self.at=0
    def detect(self,image,vision):
        w,h=image.size
        header=image.crop((0,round(h*.04),w,round(h*.21)))
        thumb=np.asarray(header.resize((320,54)))
        now=time.monotonic()
        # Inventory/task menus have a long, straight top navigation border. Do not
        # run OCR continually over the moving raid world while no menu is open.
        top=np.asarray(image.crop((0,0,w,round(h*.12))))
        edge=cv2.Canny(cv2.cvtColor(top,cv2.COLOR_RGB2GRAY),50,140)
        if not np.any(np.count_nonzero(edge[6:],axis=1)>w*.35):
            self.previous=thumb;self.scene='unknown';self.at=now;return self.scene
        if self.previous is not None and self.previous.shape==thumb.shape and now-self.at<30 and np.mean(cv2.absdiff(self.previous,thumb))<5:return self.scene
        lines=vision.text(header);words=' '.join(t.casefold().replace('ё','е') for t,_,_ in lines)
        if re.search(r'сюжетные|побочные|оперативные|main tasks|side tasks|story|история',words):scene='quests'
        elif re.search(r'схрон|stash',words):scene='stash'
        elif re.search(r'добыча|loot|труп|sport bag|спортивная сумка|контейнер|ящик|рюкзак|разгрузка|голова|headwear|tactical rig|backpack',words):scene='inventory'
        else:scene='unknown'
        self.previous=thumb;self.scene=scene;self.at=now
        return scene

def automatic_regions(window,scene,calibration=None):
    w,h=window['width'],window['height'];left,top=window['left'],window['top']
    calibration=calibration or {}
    y=round(h*calibration.get('grid_top_ratio',.044));bottom=round(h*calibration.get('grid_bottom_ratio',.96 if scene=='stash' else .879));split=round(w*calibration.get('split_ratio',.638))
    return {'inventory':{'left':left,'top':top+y,'width':split,'height':bottom-y},
        ('stash' if scene=='stash' else 'loot'):{'left':left+split+2,'top':top+y,'width':w-split-2,'height':bottom-y}}
