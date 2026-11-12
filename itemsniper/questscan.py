"""Read only visible quest titles, objective checkboxes and counters."""
from __future__ import annotations
import re
from difflib import SequenceMatcher
import cv2
import numpy as np
from .core import normalized


def key(text):return normalized(re.sub(r'\d[\d\s]*\s*/\s*\d[\d\s]*','',text)).replace('ё','е')

def match(text,entries,fields):
    value=key(text)
    if len(value)<5:return None
    ranked=[]
    for entry in entries:
        score=max((SequenceMatcher(None,value,key(entry.get(f,''))).ratio() for f in fields),default=0)
        if score>=.86:ranked.append((score,entry))
    ranked.sort(key=lambda v:-v[0])
    return ranked[0][1] if ranked and (len(ranked)==1 or ranked[0][0]-ranked[1][0]>.025) else None

def checkbox(image,box,scale=1):
    x,y=np.asarray(box).min(0);X,Y=np.asarray(box).max(0)
    array=np.asarray(image);left=max(0,round(x-65*scale));top=max(0,round(y-10*scale))
    right=max(left,round(x-2*scale));bottom=min(array.shape[0],round(Y+9*scale))
    patch=array[top:bottom,left:right]
    if not patch.size:return None
    gray=cv2.cvtColor(patch,cv2.COLOR_RGB2GRAY)
    contours,_=cv2.findContours(cv2.Canny(gray,50,140),cv2.RETR_LIST,cv2.CHAIN_APPROX_SIMPLE)
    candidates=[]
    for contour in contours:
        a,b,w,h=cv2.boundingRect(contour)
        if not 10*scale<=w<=30*scale or not .75<w/h<1.3:continue
        pad=max(3,round(3*scale));inside=gray[b+pad:b+h-pad,a+pad:a+w-pad]
        if inside.size:candidates.append((a+w,float(np.mean(inside>155))>.10))
    return max(candidates,key=lambda v:v[0])[1] if candidates else None

def parse_quests(image,lines,tasks):
    story_tasks=[t for t in tasks if t['kind']=='story']
    story=next((q for text,_,_ in lines if (q:=match(text,story_tasks,('name_ru','name_en'))) is not None),None)
    result={'quests':[],'story':None,'objectives':{},'unmatched':[]}
    if story:
        result['story']=story['id'];scale=image.height/1080
        optional_y=next((float(np.asarray(box)[:,1].min()) for text,_,box in lines if re.search(r'опциональн|optional',text,re.I)),None)
        main_y=next((float(np.asarray(box)[:,1].min()) for text,_,box in lines if re.search(r'главные задачи|main objectives',text,re.I)),image.height*.25)
        for text,confidence,box in lines:
            y=float(np.asarray(box)[:,1].mean());x=float(np.asarray(box)[:,0].min())
            if y<main_y or x>image.width*.65:continue
            o=match(text,story['objectives'],('description_ru','description_en'))
            if not o:continue
            state=checkbox(image,box,scale)
            counter=re.search(r'(\d[\d ]*)\s*/\s*(\d[\d ]*)',text)
            if state is None and not counter:continue
            count=int(counter[1].replace(' ','')) if counter else (o.get('count',1) if state else 0)
            target=int(counter[2].replace(' ','')) if counter else o.get('count',1)
            result['objectives'][o['id']]={'done':bool(state) or count>=target,'count':count,'target':target,
                'visible_optional':optional_y is not None and y>optional_y}
        # Counters may be detected as a separate line to the right of the objective.
        for oid,progress in result['objectives'].items():
            objective=next(o for o in story['objectives'] if o['id']==oid)
            label=next((box for text,_,box in lines if match(text,[objective],('description_ru','description_en'))),None)
            if label is None:continue
            cy=np.asarray(label)[:,1].mean()
            for text,_,box in lines:
                counter=re.search(r'(\d[\d ]*)\s*/\s*(\d[\d ]*)',text)
                if counter and abs(np.asarray(box)[:,1].mean()-cy)<15*scale:
                    progress['count']=int(counter[1].replace(' ',''));progress['target']=int(counter[2].replace(' ',''))
                    progress['done']=progress['done'] or progress['count']>=progress['target']
        return result
    side=[t for t in tasks if t['kind']=='side']
    for text,_,box in lines:
        q=match(text,side,('name_ru','name_en'))
        if q is None:continue
        cy=np.asarray(box)[:,1].mean()
        row=' '.join(t for t,_,b in lines if abs(np.asarray(b)[:,1].mean()-cy)<image.height*.025 and np.asarray(b)[:,0].min()>image.width*.45)
        status='complete' if re.search(r'выполнено|завершено|completed',row,re.I) else 'active' if re.search(r'активн|active|готово к сдаче',row,re.I) else None
        if status:result['quests'].append({'id':q['id'],'status':status})
    return result
