"""Passive Windows screen annotations. No interactive controls or game injection."""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import tkinter as tk


def annotation(hit, region, record, settings):
    x,y,w,h=hit['box']
    status=hit.get('status','other')
    color=settings.get({'needed':'color_needed','surplus':'color_surplus','uncertain':'color_uncertain'}.get(status,'color_other'),'#72b9eb')
    quest=bool(hit.get('quest_needed'))
    if quest:color='#ffda45'
    label=record.get('short_name_ru') or record.get('short_name') or record.get('name_ru') or hit.get('name','?')
    label=label[:24]
    if hit.get('ambiguous'):
        label='? '+label
    elif status=='surplus':
        label+=' · достаточно'
    elif hit.get('take_count'):
        label+=f" · взять {hit['take_count']}"
    return {'box':(x+region['left'],y+region['top'],w,h),'color':color,'label':label,
            'label_visible':settings['overlay_labels'],'outline_visible':settings['overlay_outlines'],'quest':quest}


class ScreenOverlay:
    TRANSPARENT='#010203'
    def __init__(self,root):
        self.window=tk.Toplevel(root)
        self.window.withdraw()
        self.window.overrideredirect(True)
        self.window.attributes('-topmost',True)
        self.window.attributes('-transparentcolor',self.TRANSPARENT)
        self.canvas=tk.Canvas(self.window,bg=self.TRANSPARENT,highlightthickness=0,borderwidth=0)
        self.canvas.pack(fill='both',expand=True)
        self.excluded_from_capture=False
        self.hwnd=None
        self.previous=None;self.visible=False

    def native_styles(self):
        if not hasattr(ctypes,'windll'):
            return
        user=ctypes.windll.user32
        user.GetAncestor.argtypes=[wintypes.HWND,wintypes.UINT]
        user.GetAncestor.restype=wintypes.HWND
        self.hwnd=user.GetAncestor(self.window.winfo_id(),2)
        getter=user.GetWindowLongPtrW if hasattr(user,'GetWindowLongPtrW') else user.GetWindowLongW
        setter=user.SetWindowLongPtrW if hasattr(user,'SetWindowLongPtrW') else user.SetWindowLongW
        getter.argtypes=[wintypes.HWND,ctypes.c_int];getter.restype=ctypes.c_ssize_t
        setter.argtypes=[wintypes.HWND,ctypes.c_int,ctypes.c_ssize_t];setter.restype=ctypes.c_ssize_t
        # WS_EX_LAYERED | TRANSPARENT | TOOLWINDOW | NOACTIVATE.
        setter(self.hwnd,-20,getter(self.hwnd,-20)|0x80000|0x20|0x80|0x08000000)
        try:
            user.SetWindowDisplayAffinity.argtypes=[wintypes.HWND,wintypes.DWORD]
            self.excluded_from_capture=bool(user.SetWindowDisplayAffinity(self.hwnd,0x11))
        except AttributeError:
            pass

    def show(self,annotations,bounds):
        if not annotations or not any(a['label_visible'] or a['outline_visible'] for a in annotations):
            return self.hide()
        if self.visible and self.previous==(annotations,bounds):return
        self.previous=(annotations,dict(bounds));self.visible=True
        left,top=bounds['left'],bounds['top']
        self.window.geometry(f"{bounds['width']}x{bounds['height']}+0+0")
        self.canvas.delete('all')
        for item in annotations:
            x,y,w,h=item['box'];x-=left;y-=top
            if item['outline_visible']:
                if item.get('quest'):
                    cx,cy=x+w/2,y+h/2;radius=min(w,h)*.29
                    self.canvas.create_oval(cx-radius,cy-radius,cx+radius,cy+radius,outline='#ffda45',width=3)
                else:self.canvas.create_rectangle(x,y,x+w,y+h,outline=item['color'],width=2)
            if item['label_visible']:
                label=self.canvas.create_text(x+3,max(2,y-15),anchor='nw',text=item['label'],fill=item['color'],font=('Segoe UI',-12,'bold'))
                box=self.canvas.bbox(label)
                background=self.canvas.create_rectangle(box[0]-2,box[1]-1,box[2]+2,box[3]+1,fill='#111111',outline='')
                self.canvas.tag_lower(background,label)
        self.window.deiconify()
        self.window.update_idletasks()
        self.native_styles()
        if self.hwnd:
            user=ctypes.windll.user32
            user.SetWindowPos.argtypes=[wintypes.HWND,wintypes.HWND,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_int,wintypes.UINT]
            user.SetWindowPos(self.hwnd,wintypes.HWND(-1),left,top,bounds['width'],bounds['height'],0x10|0x40)

    def hide(self):
        if self.visible:self.window.withdraw()
        self.visible=False;self.previous=None

    def close(self):
        self.window.destroy()
