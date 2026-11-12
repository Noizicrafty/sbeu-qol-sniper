"""Locate item rectangles from visible screen edges, without a global grid origin."""
import cv2
import numpy as np


class SlotGeometry:
    def __init__(self, image, cell=64):
        self.cell = cell
        gray = cv2.cvtColor(np.asarray(image), cv2.COLOR_RGB2GRAY)
        self.height, self.width = gray.shape
        self.vertical, self.horizontal = [], []
        self.box_cache={}
        self.caption_cache=None
        length = max(20, round(cell*.55))
        for axis in (0, 1):
            gradient = cv2.convertScaleAbs(cv2.Sobel(gray, cv2.CV_32F, 1-axis, axis, ksize=3))
            mask = (gradient > 40).astype(np.uint8)*255
            mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((5, 1) if axis == 0 else (1, 5), np.uint8))
            mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((length, 1) if axis == 0 else (1, length), np.uint8))
            _, _, stats, _ = cv2.connectedComponentsWithStats(mask)
            target = self.vertical if axis == 0 else self.horizontal
            for x, y, w, h, _ in stats[1:]:
                if (w <= 8 if axis == 0 else h <= 8):
                    target.append(tuple(map(int, (x, y, w, h))))

    def captions(self, image):
        """Locate small bright slot captions without running a text recognition model."""
        if self.caption_cache is not None:return self.caption_cache
        gray=cv2.cvtColor(np.asarray(image),cv2.COLOR_RGB2GRAY)
        result=[]
        starts=sorted({y+h//2+2 for x,y,w,h in self.horizontal})
        for start in starts:
            if start>=gray.shape[0]:continue
            mask=cv2.inRange(gray[start:start+13],135,255)
            if not mask.size:continue
            mask=cv2.morphologyEx(mask,cv2.MORPH_CLOSE,np.ones((1,4),np.uint8))
            _,_,stats,_=cv2.connectedComponentsWithStats(mask)
            for x,y,w,h,area in stats[1:]:
                if 4<=h<=13 and 9<=w<=self.cell*4 and area>=18:
                    y+=start
                    box=np.array([[x,y],[x+w,y],[x+w,y+h],[x,y+h]],dtype=np.float32)
                    if self.label_box(box) is not None:
                        result.append(box)
        self.caption_cache=result
        return result

    def label_box(self, box):
        key=tuple(np.asarray(box).ravel())
        if key not in self.box_cache:self.box_cache[key]=self._label_box(box)
        return self.box_cache[key]

    def _label_box(self, box):
        left, top = np.asarray(box).min(axis=0)
        right, bottom = np.asarray(box).max(axis=0)
        cell = self.cell
        if bottom-top > cell*.36:
            return None
        rights = [v for v in self.vertical if abs(v[0]-right) <= 12 and v[1] <= top+10 and v[1]+v[3] >= top+cell*.6]
        for rv in sorted(rights, key=lambda v: abs(v[0]-right)):
            rx = rv[0]+rv[2]//2
            tops = [h for h in self.horizontal if abs(h[1]-top) <= 10 and h[0] < left+5 and h[0]+h[2] >= rx-5]
            for ht in sorted(tops, key=lambda h: abs(h[1]-top)):
                ty = ht[1]+ht[3]//2
                # Equipped long guns can lose the left edge against the character silhouette.
                for hb in self.horizontal:
                    lx=ht[0];w=rx-lx;by=hb[1]+hb[3]//2;h=by-ty
                    if w<cell*3.7 or w>cell*8 or h<cell*1.7 or h>cell*2.3:continue
                    if abs(hb[0]-lx)>4 or abs(hb[0]+hb[2]-rx)>6:continue
                    if abs(w/cell-round(w/cell))<=.15 and abs(h/cell-round(h/cell))<=.15:
                        return (max(0,lx),max(0,ty),w,h)
                lefts = [v for v in self.vertical if v[0] <= left+3 and .70*cell <= rx-v[0] <= cell*10
                         and v[1] <= ty+8 and v[1]+v[3] >= ty+cell*.6 and ht[0] <= v[0]+5]
                for lv in sorted(lefts, key=lambda v: -v[0]):
                    lx = lv[0]+lv[2]//2
                    w = rx-lx
                    if abs(w/cell-round(w/cell)) > .18:
                        continue
                    bottoms = [h for h in self.horizontal if ty+cell*.70 <= h[1] <= ty+cell*10
                               and h[0] <= lx+5 and h[0]+h[2] >= rx-5]
                    for hb in sorted(bottoms, key=lambda h: h[1]):
                        by = hb[1]+hb[3]//2
                        h = by-ty
                        if abs(h/cell-round(h/cell)) <= .18:
                            return (max(0, lx), max(0, ty), w, h)
        # An equipment icon may touch the adjacent grid and erase its right edge.
        # Require the other three sides, with the bottom ending at the caption edge.
        # Filter once before the nested side searches. Dense cases used to test
        # every bottom edge for every left edge for every caption (millions of pairs).
        caption_bottoms=[hb for hb in self.horizontal if abs(hb[0]+hb[2]-right)<=8]
        for ht in sorted(self.horizontal,key=lambda h:abs(h[1]-top)):
            if abs(ht[1]-top)>8:break
            ty=ht[1]+ht[3]//2
            for lv in self.vertical:
                lx=lv[0]+lv[2]//2
                if lx>left+3 or ht[0]>lx+5 or lv[1]>ty+8 or lv[1]+lv[3]<ty+cell*.7:continue
                for hb in caption_bottoms:
                    rx=hb[0]+hb[2];by=hb[1]+hb[3]//2;w=rx-lx;h=by-ty
                    if abs(rx-right)>8 or hb[0]>lx+5 or ht[0]+ht[2]<rx-5:continue
                    if min(w,h)<cell*.7 or max(w,h)>cell*10:continue
                    if abs(w/cell-round(w/cell))<=.15 and abs(h/cell-round(h/cell))<=.15:
                        return (max(0,lx),max(0,ty),w,h)
        # Red lighting can hide the top border. Anchor the other sides and caption baseline.
        ty=max(0,round(top-4))
        for rv in sorted(rights,key=lambda v:abs(v[0]-right)):
            rx=rv[0]+rv[2]//2
            for lv in sorted(self.vertical,key=lambda v:-v[0]):
                lx=lv[0]+lv[2]//2;w=rx-lx
                if lx>left+3 or w<cell*.8 or w>cell*6 or abs(w/cell-round(w/cell))>.12:continue
                if lv[1]>ty+8 or lv[1]+lv[3]<ty+cell*.7:continue
                for hb in sorted(self.horizontal,key=lambda h:h[1]):
                    by=hb[1]+hb[3]//2;h=by-ty
                    if h<cell*.8 or h>cell*6 or hb[0]>lx+5 or hb[0]+hb[2]<rx-5:continue
                    if abs(h/cell-round(h/cell))<=.12:
                        return (max(0,lx),ty,w,h)
        return None

    def rectangles(self, footprints, limit=240):
        """Caption-independent closed slot boundaries, including equipment rectangles."""
        result = []
        cell = self.cell
        xs = sorted({x+w//2 for x,y,w,h in self.vertical})
        sizes = {(min(10,c),min(10,r)) for c,r in footprints}
        for x in xs:
            for X in xs:
                w = X-x
                cols = round(w/cell)
                if cols < 1 or abs(w/cell-cols) > .2:
                    continue
                horizontal = [h for h in self.horizontal if h[0] <= x+5 and h[0]+h[2] >= X-5]
                ys = sorted({y+h//2 for _,y,_,h in horizontal})
                for y in ys:
                    for Y in ys:
                        h = Y-y
                        rows = round(h/cell)
                        if (cols,rows) not in sizes or abs(h/cell-rows) > .2:
                            continue
                        if not any(abs(v[0]-x)<5 and v[1]<=y+8 and v[1]+v[3]>=min(Y,y+cell*.6) for v in self.vertical):
                            continue
                        rectangle = (x,y,w,h)
                        if rectangle not in result:
                            result.append(rectangle)
                            if len(result)>=limit:
                                return result
        return result

    def proposals(self, box, footprints):
        """Damaged borders may propose a rectangle, but only item art can confirm it."""
        left, top = np.asarray(box).min(axis=0)
        right, bottom = np.asarray(box).max(axis=0)
        if bottom-top > self.cell*.36 or right-left < 10:
            return []
        rights = [v for v in self.vertical if abs(v[0]-right) <= 12 and v[1] <= top+10 and v[1]+v[3] >= top+self.cell*.6]
        if not rights:
            return []
        rv = min(rights, key=lambda v: abs(v[0]-right))
        rx = rv[0]+rv[2]//2
        tops = [h for h in self.horizontal if abs(h[1]-top) <= 10 and h[0]+h[2] >= rx-6 and h[0] < left+5]
        ty = min(tops, key=lambda h: abs(h[1]-top))[1]+1 if tops else max(0, round(top+2))
        result = []
        for cols, rows in footprints:
            expected_w, expected_h = cols*self.cell, rows*self.cell
            lefts = [v for v in self.vertical if abs(v[0]-(rx-expected_w)) < 12 and v[1] <= ty+8 and v[1]+v[3] >= ty+self.cell*.6]
            lx = min(lefts, key=lambda v: abs(v[0]-(rx-expected_w)))[0]+1 if lefts else round(rx-expected_w)
            bottoms = [h for h in self.horizontal if abs(h[1]-(ty+expected_h)) < 10 and h[0] <= lx+5 and h[0]+h[2] >= rx-5]
            by = min(bottoms, key=lambda h: abs(h[1]-(ty+expected_h)))[1]+1 if bottoms else round(ty+expected_h)
            if 0 <= lx < rx <= self.width and 0 <= ty < by <= self.height:
                result.append((lx, ty, rx-lx, by-ty))
        return result


def waiting_regions(image, cell=64, excluded=()):
    """Find coarse diagonal hatch regions; they remain candidates for every later frame."""
    gray = cv2.cvtColor(np.asarray(image),cv2.COLOR_RGB2GRAY)
    size = max(24,round(cell*.75))
    step = max(16,size//2)
    window = np.outer(np.hanning(size),np.hanning(size))
    fy,fx = np.meshgrid(np.fft.fftfreq(size),np.fft.fftfreq(size),indexing='ij')
    radius = np.sqrt(fx*fx+fy*fy)
    band = (radius>1/28)&(radius<1/5)
    diagonal = band & (np.abs(np.abs(fx)-np.abs(fy))<.025)
    mask = np.zeros_like(gray,dtype=np.uint8)
    for y in range(0,max(0,gray.shape[0]-size+1),step):
        for x in range(0,max(0,gray.shape[1]-size+1),step):
            patch = gray[y:y+size,x:x+size].astype(np.float32)
            if patch.std()<5:
                continue
            power = np.abs(np.fft.fft2((patch-patch.mean())*window))**2
            energy = power[band].sum()
            if energy>1000 and power[diagonal].sum()/energy>.78 and energy/max(1,power.sum())>.25:
                mask[y:y+size,x:x+size]=255
    for x,y,w,h in excluded:
        mask[max(0,y):y+h,max(0,x):x+w]=0
    _,_,stats,_ = cv2.connectedComponentsWithStats(mask)
    return [tuple(map(int,row[:4])) for row in stats[1:] if row[2]>=size and row[3]>=size]

