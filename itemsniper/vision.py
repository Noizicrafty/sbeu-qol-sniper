from __future__ import annotations

import math
import re
import time
import copy
from pathlib import Path

import cv2
import mss
import numpy as np
from PIL import Image

from .catalog import item_records
from .core import normalized
from .slots import SlotGeometry, waiting_regions


def capture(region):
    with mss.mss() as screen:
        return Image.frombytes('RGB', (region['width'], region['height']), screen.grab(region).rgb)


def aliases(record):
    return {normalized(str(record.get(key, ''))).replace('ё', 'е')
            for key in ('name', 'display_name', 'name_ru', 'short_name', 'short_name_ru')} - {''}


def caption_key(text):
    # Compact equipment captions often render б as 6 and the separating dot as
    # a colon. Normalize only the Sb magazine designation, not arbitrary names.
    text=re.sub(r'(?i)\b[cс][бb6]\s*[.:]?\s*3\s*[xх]\s*(\d+)',r'сб.3x\1',text)
    table=str.maketrans({'а':'a','в':'b','е':'e','ё':'e','к':'k','м':'m','н':'h','о':'o','р':'p','с':'c',
                        'т':'t','у':'y','х':'x','з':'z','л':'l','и':'n','u':'n','0':'o','3':'z'})
    return normalized(text).translate(table)


def overlap(a, b):
    x, y, w, h = a
    X, Y, W, H = b
    intersection = max(0, min(x+w, X+W)-max(x, X)) * max(0, min(y+h, Y+H)-max(y, Y))
    return intersection / max(1, min(w*h, W*H))


class Vision:
    def __init__(self):
        self.engines = {}
        self.templates = {}
        self.alias_cache = None
        self.last_analysis = {}
        self.library = None
        self.frame_cache = {}
        self.art_cache = {}
        self.caption_engines=[]
        self.caption_ready=False
        cv2.setNumThreads(1)

    def scan(self, image, catalog, threshold=.88, slot_size=64, view_key='loot', fast=False):
        """Re-read changed patches; unrevealed cells never become permanently empty."""
        array=np.asarray(image)
        generation=(id(catalog),threshold,slot_size,self.library.status.get('indexed',0) if self.library else 0,fast,self.caption_ready)
        previous=self.frame_cache.get(view_key)
        now=time.monotonic()
        if previous and previous['array'].shape==array.shape and previous['generation']==generation and now-previous['full_at']<30:
            difference=cv2.absdiff(cv2.cvtColor(array,cv2.COLOR_RGB2GRAY),cv2.cvtColor(previous['array'],cv2.COLOR_RGB2GRAY))
            mask=(difference>18).astype(np.uint8)*255
            if np.count_nonzero(mask)<max(12,array.shape[0]*array.shape[1]*.0001):
                self.last_analysis=copy.deepcopy(previous['analysis'])
                self.last_analysis['frame_reused']=True
                return copy.deepcopy(previous['hits'])
            mask=cv2.morphologyEx(mask,cv2.MORPH_CLOSE,np.ones((15,15),np.uint8))
            _,_,stats,_=cv2.connectedComponentsWithStats(mask)
            merged=[]
            for x,y,w,h,area in stats[1:]:
                if area<12:
                    continue
                rectangle=[max(0,int(x)-slot_size),max(0,int(y)-slot_size),min(array.shape[1],int(x+w)+slot_size),min(array.shape[0],int(y+h)+slot_size)]
                if fast:
                    # Keep the grid's row anchors: some item borders are interrupted by art.
                    rectangle[0],rectangle[2]=0,array.shape[1]
                for other in merged:
                    if rectangle[0]<=other[2] and rectangle[2]>=other[0] and rectangle[1]<=other[3] and rectangle[3]>=other[1]:
                        other[:]=[min(other[0],rectangle[0]),min(other[1],rectangle[1]),max(other[2],rectangle[2]),max(other[3],rectangle[3])]
                        break
                else:
                    merged.append(rectangle)
            # Never crop through an existing multi-cell object; merge transitively.
            for rectangle in merged:
                for hit in previous['hits']:
                    x,y,w,h=hit['box']
                    if rectangle[0]<x+w and rectangle[2]>x and rectangle[1]<y+h and rectangle[3]>y:
                        rectangle[:]=[min(rectangle[0],x),min(rectangle[1],y),max(rectangle[2],x+w),max(rectangle[3],y+h)]
            changed=True
            while changed:
                changed=False
                for i in range(len(merged)):
                    for j in range(i+1,len(merged)):
                        a,b=merged[i],merged[j]
                        if a[0]<=b[2] and a[2]>=b[0] and a[1]<=b[3] and a[3]>=b[1]:
                            a[:]=[min(a[0],b[0]),min(a[1],b[1]),max(a[2],b[2]),max(a[3],b[3])]
                            merged.pop(j);changed=True;break
                    if changed:break
            if merged and len(merged)<=4 and sum((r[2]-r[0])*(r[3]-r[1]) for r in merged)<array.shape[0]*array.shape[1]*.6:
                def affected(box):
                    x,y,w,h=box
                    return any(max(x,r[0])<min(x+w,r[2]) and max(y,r[1])<min(y+h,r[3]) for r in merged)
                hits=[hit for hit in previous['hits'] if not affected(hit['box'])]
                waiting=[box for box in previous['analysis'].get('waiting',[]) if not affected(box)]
                analysis=copy.deepcopy(previous['analysis'])
                for x0,y0,x1,y1 in merged:
                    additions=self.items(Image.fromarray(array[y0:y1,x0:x1]),catalog,threshold,slot_size,**({'fast':True} if fast else {}))
                    for hit in additions:
                        hit=copy.deepcopy(hit);x,y,w,h=hit['box'];hit['box']=(x+x0,y+y0,w,h)
                        if not any(overlap(hit['box'],old['box'])>.4 for old in hits):
                            hits.append(hit)
                    waiting.extend((x+x0,y+y0,w,h) for x,y,w,h in self.last_analysis.get('waiting',[]))
                analysis['waiting']=waiting
                analysis['incremental']=True
                analysis['changed_regions']=merged
                self.last_analysis=analysis
                self.frame_cache[view_key]={'array':array.copy(),'generation':generation,'hits':copy.deepcopy(hits),
                    'analysis':copy.deepcopy(analysis),'full_at':previous['full_at']}
                return hits
        hits=self.items(image,catalog,threshold,slot_size,**({'fast':True} if fast else {}))
        self.frame_cache[view_key]={'array':array.copy(),'generation':generation,'hits':copy.deepcopy(hits),
            'analysis':copy.deepcopy(self.last_analysis),'full_at':now}
        return hits

    def text(self, image):
        from rapidocr import RapidOCR
        from rapidocr.utils.typings import LangRec, ModelType, OCRVersion
        lines = []
        for language in (LangRec.CYRILLIC, LangRec.EN):
            if language.value not in self.engines:
                self.engines[language.value] = RapidOCR(params={
                    'Global.use_cls':False,
                    'Rec.lang_type': language, 'Rec.ocr_version': OCRVersion.PPOCRV5,
                    'Rec.model_type': ModelType.MOBILE,'EngineConfig.onnxruntime.intra_op_num_threads':2,
                    'EngineConfig.onnxruntime.inter_op_num_threads':1})
            result = self.engines[language.value](np.asarray(image))
            if result.txts is not None:
                for text, score, box in zip(result.txts, result.scores, result.boxes):
                    if score >= .70:
                        lines.append((str(text), float(score), np.asarray(box)))
        return lines

    def prepare_caption_ocr(self):
        from rapidocr import RapidOCR
        from rapidocr.utils.typings import LangRec,ModelType,OCRVersion
        engines=[]
        for language in (LangRec.CYRILLIC,LangRec.EN):
            engine=RapidOCR(params={'Rec.lang_type':language,'Rec.ocr_version':OCRVersion.PPOCRV5,
                'Rec.model_type':ModelType.MOBILE,'Rec.rec_img_shape':[3,48,96],
                'EngineConfig.onnxruntime.intra_op_num_threads':2,
                'EngineConfig.onnxruntime.inter_op_num_threads':1})
            engine.recognize_txt([np.zeros((32,96,3),dtype=np.uint8)])
            engines.append(engine)
        self.caption_engines=engines
        self.caption_ready=True

    def slot_text(self,image,captions,known=None):
        if not self.caption_ready or not captions:return []
        array=np.asarray(image);patches=[];boxes=[]
        seen=set()
        for box in captions:
            x,y=np.asarray(box).min(0).astype(int);X,Y=np.asarray(box).max(0).astype(int)
            key=(x//3,y//3,X//3)
            if key in seen:continue
            seen.add(key)
            patch=array[max(0,y-1):min(array.shape[0],y+12),max(0,x-2):min(array.shape[1],X+2)]
            if not patch.size:continue
            patches.append(cv2.resize(patch,None,fx=3,fy=3));boxes.append(box)
        lines=[]
        for engine in self.caption_engines:
            if not patches:break
            result=engine.recognize_txt(patches)
            if result.txts is not None:
                lines.extend((str(text),float(score),box) for text,score,box in zip(result.txts,result.scores,boxes) if score>=.70)
                if known is not None:
                    unresolved=[i for i,(text,score) in enumerate(zip(result.txts,result.scores)) if score<.94 or len(known.get(caption_key(str(text)),()))!=1]
                    patches=[patches[i] for i in unresolved];boxes=[boxes[i] for i in unresolved]
        return lines

    def hideout(self, image, catalog):
        lines = self.text(image)
        candidates = {}
        for station in catalog.get('stations', []):
            for text, _, box in lines:
                if not any(name in normalized(text).replace('ё', 'е') for name in aliases(station)):
                    continue
                nearby = [(t, b) for t, _, b in lines
                          if abs(float(b[:, 1].mean() - box[:, 1].mean())) < 130
                          and abs(float(b[:, 0].mean() - box[:, 0].mean())) < 450]
                for value, _ in [(text, box)] + nearby:
                    match = re.search(r'(?:level|lvl|уровень|ур\.?)[\s:.-]*(\d+)', value, re.I)
                    maximum = max((x['level'] for x in station['levels']), default=5)
                    if match and int(match.group(1)) <= maximum:
                        candidates[station['name']] = int(match.group(1))
                        break
        return candidates, '\n'.join(dict.fromkeys(t for t, _, _ in lines))

    def load_template(self, path):
        if path not in self.templates:
            if len(self.templates)>=8192:
                self.templates.pop(next(iter(self.templates)))
            self.templates[path] = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_UNCHANGED) if Path(path).exists() else None
        return self.templates[path]

    @staticmethod
    def checkmark(image, box, custom_template=None, cell=64):
        """Unknown badge never counts as FIR; inspect only the slot's bottom right."""
        x, y, w, h = map(int, box)
        array = np.asarray(image)
        # Resource counters move the FIR badge above the bottom text line.
        patch = array[max(0, y+h-round(42*cell/64)):min(array.shape[0], y+h), max(0, x+w-round(32*cell/64)):min(array.shape[1], x+w)]
        if patch.shape[0] < 8 or patch.shape[1] < 8:
            return 'unknown', 0.
        gray = cv2.cvtColor(patch, cv2.COLOR_RGB2GRAY)
        if custom_template is not None:
            template = cv2.cvtColor(custom_template[:, :, :3], cv2.COLOR_BGR2GRAY) if custom_template.ndim == 3 else custom_template
            if template.shape[0] <= gray.shape[0] and template.shape[1] <= gray.shape[1] and template.std() > 2:
                score = float(cv2.minMaxLoc(cv2.matchTemplate(gray, template, cv2.TM_CCOEFF_NORMED))[1])
                if score >= .90:
                    return 'yes', score
                return ('no', score) if gray.max() < 120 else ('unknown', score)
        bright = cv2.inRange(patch, np.array([175, 175, 175]), np.array([255, 255, 255]))
        lines = cv2.HoughLinesP(cv2.Canny(bright, 60, 140), 1, np.pi/180, threshold=5, minLineLength=4, maxLineGap=1)
        strokes = []
        if lines is not None:
            for X, Y, X2, Y2 in lines[:, 0]:
                if X2 < X:
                    X, Y, X2, Y2 = X2, Y2, X, Y
                if X2 != X:
                    strokes.append((int(X), int(Y), int(X2), int(Y2), (Y2-Y)/(X2-X)))
        for a in strokes:
            for b in strokes:
                if .45 < a[4] < 1.8 and -1.8 < b[4] < -.45:
                    if math.dist(a[2:4], b[:2]) <= 4 and b[2]-b[0] >= a[2]-a[0]:
                        return 'yes', .85
        return ('no', 0.) if gray.max() < 120 else ('unknown', 0.)

    def slot_images(self, frame, templates, rectangles, threshold, cell):
        found = []
        for name, path in templates.items():
            rotations=range(4)
            if isinstance(path,dict):
                # Labels stay upright in game when an icon is rotated. Coarse
                # retrieval can therefore prefer the opposite orientation of
                # the same public image; verify both instead of losing the item.
                rotations=path.get('rotations',(path['rotation'],(path['rotation']+2)%4))
                path=path['path']
            cache_key=(path,'gray')
            base=self.art_cache.get(cache_key)
            if base is None:
                raw = self.load_template(path)
                if raw is None:
                    continue
                base = cv2.cvtColor(raw[:, :, :3], cv2.COLOR_BGR2GRAY) if raw.ndim == 3 else raw
                self.art_cache[cache_key]=base
            for turns in rotations:
                icon = np.ascontiguousarray(np.rot90(base, turns))
                for x, y, w, h in rectangles:
                    if abs((w/h)/(icon.shape[1]/icon.shape[0])-1) > .18:
                        continue
                    patch = frame[y:y+h, x:x+w]
                    if patch.shape != (h, w):
                        continue
                    score = -1.
                    for width in {w, w+1, round(icon.shape[1]*cell/64)}:
                        height = round(icon.shape[0]*width/icon.shape[1])
                        if abs(height-h) > 10:
                            continue
                        dx, dy = max(2, round(width*.12)), max(3, round(min(height, cell)*.24))
                        bottom = max(3, round(min(height, cell)*.24))
                        key=(path,turns,width,height)
                        art=self.art_cache.get(key)
                        if art is None:
                            resized = cv2.resize(icon, (width, height))
                            art=resized[dy:height-bottom, dx:width-dx]
                            if art.size==0 or art.std()<5:
                                continue
                            self.art_cache[key]=art
                        target = frame[max(0,y+dy-8):y+height-bottom+8, max(0,x+dx-8):x+width-dx+8]
                        if target.shape[0] < art.shape[0] or target.shape[1] < art.shape[1]:
                            continue
                        value = cv2.minMaxLoc(cv2.matchTemplate(target, art, cv2.TM_CCOEFF_NORMED))[1]
                        score = max(score, float(value))
                    if score >= threshold:
                        found.append({'name': name, 'score': score, 'box': (x, y, w, h),
                                      'method': 'slot-image', 'count': 1,'rotation':int(turns*90)})
        return found

    def items(self, image, catalog, threshold=.88, slot_size=64, names=None, fast=False, geometry=None, seed_hits=None, focus=None):
        array=np.asarray(image)
        frame = cv2.cvtColor(array, cv2.COLOR_RGB2GRAY)
        lines = [] if fast else self.text(image)
        geometry = geometry if geometry is not None else SlotGeometry(image, slot_size)
        captions=[box for _,_,box in lines] if not fast else geometry.captions(image)
        slot_boxes = []
        def relevant(box):
            if focus is None:return True
            x,y,w,h=box;X,Y,W,H=focus
            return max(x,X)<min(x+w,X+W) and max(y,Y)<min(y+h,Y+H)
        for caption in captions:
            rectangle = geometry.label_box(caption)
            if rectangle and relevant(rectangle) and rectangle not in slot_boxes:
                slot_boxes.append(rectangle)
        found = []
        templates = {**catalog.get('icons', {}), **catalog.get('grid_templates', {})}
        if names is not None and self.library is None:
            templates = {name: path for name, path in templates.items() if name in names}
        footprints = set(self.library.footprints) if self.library else set()
        for path in (() if self.library else templates.values()):
            template = self.load_template(path)
            if template is not None:
                cols, rows = max(1, round(template.shape[1]/64)), max(1, round(template.shape[0]/64))
                footprints.update(((cols, rows), (rows, cols)))
        for caption in (() if fast else captions):
            if geometry.label_box(caption) is None:
                for rectangle in geometry.proposals(caption, footprints):
                    if rectangle not in slot_boxes:
                        slot_boxes.append(rectangle)
        if seed_hits is not None:
            found=copy.deepcopy(seed_hits)
        elif self.library and self.library.status.get('indexed'):
            for rectangle in (() if fast else geometry.rectangles(footprints)):
                if rectangle not in slot_boxes:
                    slot_boxes.append(rectangle)
            patches,valid_rectangles=[],[]
            for rectangle in slot_boxes[:300]:
                x,y,w,h = rectangle
                patch = array[y:y+h,x:x+w]
                if not patch.size or cv2.cvtColor(patch,cv2.COLOR_RGB2GRAY).std()<5:
                    continue
                patches.append(patch);valid_rectangles.append(rectangle)
            for rectangle,candidates in zip(valid_rectangles,self.library.retrieve_many(patches,limit=16)):
                found.extend(self.slot_images(frame,candidates,[rectangle],threshold,slot_size))
        elif slot_boxes:
            found = self.slot_images(frame, templates, slot_boxes, threshold, slot_size)
        else:
            for name, path in templates.items():
                raw = self.load_template(path)
                if raw is None:
                    continue
                base = cv2.cvtColor(raw[:, :, :3], cv2.COLOR_BGR2GRAY) if raw.ndim == 3 else raw
                for turns in range(4):
                    icon = np.ascontiguousarray(np.rot90(base, turns))
                    for scale in (slot_size/64*.9, slot_size/64, slot_size/64*1.1):
                        w, h = round(icon.shape[1]*scale), round(icon.shape[0]*scale)
                        if min(w, h) < 20 or h > frame.shape[0] or w > frame.shape[1]:
                            continue
                        template = cv2.resize(icon, (w, h))
                        # Mask label, count, checkmark and border by matching only central art.
                        dx, dy = max(2, round(w*.12)), max(3, round(min(h, slot_size)*.24))
                        bottom = max(3, round(min(h, slot_size)*.24))
                        art = template[dy:h-bottom, dx:w-dx]
                        if art.size == 0 or art.std() < 5:
                            continue
                        scores = cv2.matchTemplate(frame, art, cv2.TM_CCOEFF_NORMED)
                        for _ in range(60):
                            _, score, _, (X, Y) = cv2.minMaxLoc(scores)
                            if score < threshold:
                                break
                            x, y = X-dx, Y-dy
                            if x >= 0 and y >= 0 and x+w <= frame.shape[1]+2 and y+h <= frame.shape[0]+2:
                                found.append({'name': name, 'score': float(score), 'box': (x, y, w, h), 'method': 'slot-image', 'count': 1})
                            scores[max(0, Y-h//2):Y+h//2+1, max(0, X-w//2):X+w//2+1] = -1
        kept = []
        for hit in sorted(found, key=lambda h: h['score'], reverse=True):
            if not any(overlap(hit['box'], other['box']) > .40 for other in kept):
                alternatives=sorted({other['name'] for other in found if other['name']!=hit['name']
                                     and overlap(hit['box'],other['box'])>.7 and hit['score']-other['score']<.008})
                if alternatives:
                    hit={**hit,'ambiguous':True,'candidates':[hit['name']]+alternatives}
                kept.append(hit)
        # Only calibrated slot labels are eligible; no inspect-window / tooltip fallback.
        records = item_records(catalog)
        key = (id(catalog), len(records))
        if self.alias_cache is None or self.alias_cache[0] != key:
            alias_map = {}
            for name, record in records.items():
                for alias in aliases(record):
                    alias_map.setdefault(caption_key(alias), set()).add(name)
            self.alias_cache = (key, alias_map)
        index = self.alias_cache[1]
        if fast and self.caption_ready:
            missing={}
            for box in captions:
                footprint=geometry.label_box(box)
                if footprint is None or not relevant(footprint) or any(overlap(footprint,hit['box'])>.4 for hit in kept):continue
                left,top=np.asarray(box).min(0);right,bottom=np.asarray(box).max(0)
                if not 0<=top-footprint[1]<=10:continue
                key=tuple(round(value/8) for value in footprint)
                rank=(abs(top-footprint[1]-4),-(right-left))
                if key not in missing or rank<missing[key][0]:missing[key]=(rank,box)
            lines=self.slot_text(image,[value[1] for value in missing.values()],index)
        self.last_analysis = {'search_in_progress': any(re.search(r'(ид[её]т\s*поиск|searching)', text, re.I) for text, _, _ in lines),
                              'unsearched': any(re.search(r'(не\s*обыскано|unsearched)', text, re.I) for text, _, _ in lines),
                              'waiting': [],'panel_visible': len(geometry.vertical)>=3 and len(geometry.horizontal)>=2,
                              'indexed_items': self.library.status.get('indexed',0) if self.library else len(templates)}
        for text, score, box in lines:
            matches = index.get(caption_key(text), set())
            if not matches:
                continue
            footprint = geometry.label_box(box)
            if footprint is None:
                # Legacy calibration only for synthetic/borderless inputs, not real multi-grid frames.
                x, y = box.min(axis=0)
                width, height = box.max(axis=0)-box.min(axis=0)
                cell_x, cell_y = math.floor(x/slot_size)*slot_size, math.floor(y/slot_size)*slot_size
                if geometry.vertical or geometry.horizontal or height > slot_size*.35 or width > slot_size*3 or x-cell_x > slot_size*.30 or y-cell_y > slot_size*.30:
                    continue
                footprint = (cell_x, cell_y, slot_size, slot_size)
            if any(overlap(footprint, hit['box']) > .35 for hit in kept):
                continue
            options = sorted(matches)
            if self.library:
                # A single-cell part must not identify a two-cell magazine from a split caption.
                if not hasattr(self,'shape_lookup') or self.shape_lookup[0]!=id(self.library.names):
                    self.shape_lookup=(id(self.library.names),{name:(w,h) for name,(w,h) in zip(self.library.names,self.library.dimensions)})
                sizes=self.shape_lookup[1]
                cells=sorted(round(value/slot_size) for value in footprint[2:])
                if len(caption_key(text).replace(' ',''))<=3 and cells[0]==1 and cells[1]<=6:
                    options=[name for name in options if name not in sizes or sorted(round(value/64) for value in sizes[name])==cells]
                if not options:continue
            # Repeated short names never silently select a preset/weapon/magazine variant.
            kept.append({'name': options[0], 'score': score, 'box': footprint, 'method': 'slot-label', 'count': 1,
                         'ambiguous':len(options)>1,'candidates':options if len(options)>1 else []})
        default_fir = Path(__file__).with_name('assets') / 'fir-checkmark.png'
        fir_path = catalog.get('fir_template') or (str(default_fir) if default_fir.exists() else None)
        fir_template = self.load_template(fir_path) if fir_path else None
        if fir_template is not None and slot_size!=64:
            fir_template=cv2.resize(fir_template,None,fx=slot_size/64,fy=slot_size/64)
        for hit in kept:
            hit['fir'], hit['fir_score'] = self.checkmark(image, hit['box'], fir_template,slot_size)
            x, y, w, h = hit['box']
            quantities = []
            for text, score, box in lines:
                if re.search(r'dogtag|magazine',hit['name'],re.I):
                    continue
                if not re.fullmatch(r'\d{1,7}', text.strip()):
                    continue
                cx, cy = box.mean(axis=0)
                if x+w-slot_size*.55 <= cx < x+w and y+h-slot_size*.35 <= cy < y+h:
                    quantities.append((score, int(text.strip())))
            if quantities:
                score, count = max(quantities)
                if count > 0:
                    hit['count'], hit['count_score'] = count, score
        self.last_analysis['waiting'] = waiting_regions(image,slot_size,excluded=[hit['box'] for hit in kept])
        return kept
