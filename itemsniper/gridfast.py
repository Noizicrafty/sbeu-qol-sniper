"""Slot bounds in a visibly open, normalized rectangular storage grid."""
import cv2
import numpy as np
from pathlib import Path


def badges(vision,image,hits):
    template=vision.load_template(str(Path(__file__).with_name('assets')/'fir-checkmark.png'))
    for hit in hits:hit['fir'],hit['fir_score']=vision.checkmark(image,hit['box'],template,64)
    return hits


def caption_anchors(image,cell=64):
    gray=cv2.cvtColor(np.asarray(image),cv2.COLOR_RGB2GRAY);height,width=gray.shape;result=[]
    for y in range(0,height,cell):
        band=gray[y+1:min(height,y+16)]
        mask=cv2.morphologyEx(cv2.inRange(band,100,255),cv2.MORPH_CLOSE,np.ones((1,4),np.uint8))
        # Blue slot borders can connect an otherwise isolated short caption to
        # the entire row. Split only the border before finding text components.
        for edge in range(cell,width,cell):mask[:,edge-2:edge+2]=0
        _,_,stats,_=cv2.connectedComponentsWithStats(mask)
        for x,Y,w,h,area in stats[1:]:
            if not (4<=h<=15 and 9<=w<=cell*5 and area>=18):continue
            right=round((x+w)/cell)*cell
            if not cell<=right<=width or abs(x+w-right)>14:continue
            result.append(np.asarray([[x,y+Y+1],[x+w,y+Y+1],[x+w,y+Y+h+1],[x,y+Y+h+1]],dtype=np.float32))
    return result


def read_grid_batch(vision,image,captions,catalog):
    """Public footprints + visible caption; compare art to resolve orientation."""
    from .vision import caption_key
    from .catalog import item_records
    records=item_records(catalog);index=vision.alias_cache[1]
    lines=vision.slot_text(image,captions,index);gray=cv2.cvtColor(np.asarray(image),cv2.COLOR_RGB2GRAY);hits=[]
    vx=cv2.convertScaleAbs(cv2.Sobel(gray,cv2.CV_32F,1,0));hy=cv2.convertScaleAbs(cv2.Sobel(gray,cv2.CV_32F,0,1))
    def boundary_score(box):
        x,y,w,h=box;sides=[]
        for X in (x,x+w):
            line=vx[y+4:y+h-4,max(0,X-3):min(image.width,X+4)]
            sides.append(float(np.mean(np.max(line,axis=1)>45)) if line.size else 1.)
        for Y in (y,y+h):
            line=hy[max(0,Y-3):min(image.height,Y+4),x+4:x+w-4]
            sides.append(float(np.mean(np.max(line,axis=0)>45)) if line.size else 1.)
        return sum(sides)/4
    library=vision.library
    if not hasattr(vision,'grid_paths') or vision.grid_paths[0]!=id(library.names):
        vision.grid_paths=(id(library.names),dict(zip(library.names,library.paths)))
    paths=vision.grid_paths[1]
    for text,score,caption in lines:
        options=sorted(index.get(caption_key(text),()))
        if not options:continue
        right=round(float(caption[:,0].max())/64)*64;y=int(float(caption[:,1].min())//64)*64
        for name in options:
            record=records.get(name,{});w,h=int(record.get('width',1))*64,int(record.get('height',1))*64
            boxes=[(right-W,y,W,H) for W,H in {(w,h),(h,w)} if right-W>=0 and y+H<=image.height]
            if not boxes:continue
            path=paths.get(name)
            matched=vision.slot_images(gray,{name:path},boxes,.86,64) if path else []
            if matched:
                hit=max(matched,key=lambda hit:hit['score'])
            elif (len(boxes)==1 or w==h) and score>=.9:
                hit={'name':name,'box':boxes[0],'score':score,'method':'grid-caption','count':1,'ambiguous':len(options)>1,'candidates':options if len(options)>1 else []}
            else:
                ranked=sorted(((boundary_score(box),box) for box in boxes),reverse=True)
                if score<.9 or len(ranked)<2 or ranked[0][0]<.65 or ranked[0][0]-ranked[1][0]<.1:continue
                hit={'name':name,'box':ranked[0][1],'score':score,'method':'grid-caption-edges','count':1,'ambiguous':len(options)>1,'candidates':options if len(options)>1 else []}
            if not any(old['name']==name and old['box']==hit['box'] for old in hits):hits.append(hit)
    return badges(vision,image,hits)


def grid_image_stream(vision,image,captions):
    """Batch visual retrieval over plausible footprints, without any OCR wait."""
    from .vision import overlap
    array=np.asarray(image);gray=cv2.cvtColor(array,cv2.COLOR_RGB2GRAY)
    shapes=sorted((shape for shape in vision.library.footprints if max(shape)<=8 and shape[0]*shape[1]<=24),key=lambda s:(s[0]*s[1],max(s),s))
    # Retrieve the common shapes together before verifying. Otherwise an item
    # with two cells waits behind every one-cell candidate in a packed case.
    common={(1,1),(1,2),(2,1),(1,3),(3,1),(2,2),(2,3),(3,2)}
    proposals=[]
    for cols,rows in (s for s in shapes if s in common):
        boxes=[]
        for caption in captions:
            right=round(float(caption[:,0].max())/64)*64;y=int(float(caption[:,1].min())//64)*64
            box=(right-cols*64,y,cols*64,rows*64)
            if box[0]>=0 and y+rows*64<=image.height and box not in boxes:boxes.append(box)
        patches=[array[y:y+h,x:x+w] for x,y,w,h in boxes]
        for box,candidates in zip(boxes,vision.library.retrieve_many(patches,16)):
            best=max((v['coarse_score'] for v in candidates.values()),default=0)
            if best>=.83:proposals.append((best,box,{k:v for k,v in candidates.items() if v['coarse_score']>=best-.015}))
    confirmed=[]
    proposals.sort(key=lambda p:-p[0])
    for offset in range(0,len(proposals),8):
        found=[]
        for _,box,candidates in proposals[offset:offset+8]:
            if any(overlap(box,old['box'])>.5 for old in confirmed):continue
            matches=vision.slot_images(gray,candidates,[box],.9,64)
            if not matches:continue
            hit=max(matches,key=lambda h:h['score'])
            variants=sorted({other['name'] for other in matches if other['name']!=hit['name'] and hit['score']-other['score']<.008})
            if variants:hit={**hit,'ambiguous':True,'candidates':[hit['name']]+variants}
            confirmed.append(hit);found.append(hit)
        yield badges(vision,image,found)
    shapes=[shape for shape in shapes if shape not in common]
    for cols,rows in shapes:
        rectangles=[]
        for caption in captions:
            right=round(float(caption[:,0].max())/64)*64;y=int(float(caption[:,1].min())//64)*64
            box=(right-cols*64,y,cols*64,rows*64)
            if box[0]>=0 and box[1]+box[3]<=image.height and box not in rectangles:rectangles.append(box)
        for offset in range(0,len(rectangles),16):
            boxes=rectangles[offset:offset+16];patches=[array[y:y+h,x:x+w] for x,y,w,h in boxes];found=[]
            for box,candidates in zip(boxes,vision.library.retrieve_many(patches,16)):
                best=max((v['coarse_score'] for v in candidates.values()),default=0)
                # First display the nearest visual family, retaining tied
                # variants. General refinement still checks the wider shortlist.
                candidates={k:v for k,v in candidates.items() if v['coarse_score']>=max(.83,best-.015)}
                found.extend(vision.slot_images(gray,candidates,[box],.9,64))
            kept=[]
            for hit in sorted(found,key=lambda h:h['score'],reverse=True):
                if any(overlap(hit['box'],old['box'])>.4 for old in kept):continue
                alternatives=sorted({other['name'] for other in found if other['name']!=hit['name'] and overlap(hit['box'],other['box'])>.7 and hit['score']-other['score']<.008})
                if alternatives:hit={**hit,'ambiguous':True,'candidates':[hit['name']]+alternatives}
                kept.append(hit)
            yield badges(vision,image,kept)
