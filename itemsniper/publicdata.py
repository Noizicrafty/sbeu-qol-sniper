"""Read public reference data. Never requests an account, profile or game endpoint."""
from __future__ import annotations
import copy
import json
import time
import re
from pathlib import Path
import requests
from .core import save_json

BASE='https://json.tarkov.dev/'
STORY='https://szepiz.github.io/tarkov-quest-data/api/maps.json'

def download(directory,mode='pve',refresh=False):
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    for name in ('tasks','hideout','items','traders','maps'):
        for suffix in ('','_ru','_en'):
            path=directory/f'{name}{suffix}.json'
            if path.exists() and not refresh:continue
            r=requests.get(f'{BASE}{mode}/{name}{suffix}',timeout=70)
            if r.status_code==404 and suffix:continue
            r.raise_for_status();save_json(path,r.json())
    r=requests.get(STORY,timeout=40);r.raise_for_status();save_json(directory/'storymaps.json',r.json())
    path=directory/'regular-tasks.json'
    if refresh or not path.exists():
        r=requests.get(BASE+'regular/tasks',timeout=70);r.raise_for_status();save_json(path,r.json())

def normalize(directory,mode='pve'):
    directory=Path(directory)
    def read(name):
        p=directory/f'{name}.json'
        return json.loads(p.read_text(encoding='utf8')) if p.exists() else {}
    def data(name):return read(name).get('data',{})
    tr={lang:{**data('items_'+lang),**data('tasks_'+lang),**data('hideout_'+lang),**data('maps_'+lang),**data('traders_'+lang)} for lang in ('ru','en')}
    def text(key,lang,fallback=''):return tr[lang].get(key,fallback or key)
    tasks=data('tasks');items=data('items');maps=data('maps');traders=data('traders')
    categories=items.get('itemCategories',{})
    catalog=[]
    for source in list(items.get('items',{}).values())+list(tasks.get('questItems',{}).values()):
        value={'id':source['id'],'name':text(source['name'],'en'), 'name_ru':text(source['name'],'ru'),
            'short_name':text(source.get('shortName',''),'en'), 'short_name_ru':text(source.get('shortName',''),'ru'),
            'grid_url':source.get('gridImageLink',''),'icon_url':source.get('iconLink',''),'wiki':source.get('wikiLink',''),
            'types':source.get('types',['quest']),'width':source.get('width',1),'height':source.get('height',1),
            'categories':[{'id':cid,'name':text(categories.get(cid,{}).get('name',cid),'ru')} for cid in source.get('categories',[])],
            'source':BASE+mode+'/items'}
        catalog.append(value)
    by_id={v['id']:v for v in catalog}
    named_catalog=[(re.sub(r'[^a-z0-9]+',' ',v['name'].casefold()).strip(),v) for v in catalog]
    def objective(source):
        value=copy.deepcopy(source)
        value['description_en']=text(source.get('description',''),'en',source.get('description',''))
        value['description_ru']=text(source.get('description',''),'ru',value['description_en'])
        value['count']=int(source.get('count') or 1)
        value['optional']=bool(source.get('optional',False))
        value['items']=list(source.get('items',[]))
        if source.get('questItem'):value['items'].append(source['questItem'])
        if source.get('item'):value['items'].append(source['item'])
        labels=[]
        if source.get('foundInRaid'):labels.append('Только найденные в рейде (FIR)')
        names={'accuracy':'Точность','durability':'Прочность','effectiveDistance':'Прицельная дальность','ergonomics':'Эргономика','height':'Высота','width':'Ширина','magazineCapacity':'Ёмкость магазина','muzzleVelocity':'Начальная скорость','recoil':'Отдача','weight':'Вес'}
        for key,condition in (source.get('buildAttributes') or {}).items():
            if condition.get('value'):labels.append(f"{names.get(key,key)}: {condition.get('compareMethod','')} {condition['value']}")
        def ids(value):
            if isinstance(value,str):return [value]
            if isinstance(value,list):return [iid for v in value for iid in ids(v)]
            return []
        for field,label in [('containsAll','Установленные детали'),('usingWeapon','Оружие'),('usingWeaponMods','Модификации'),('wearing','Экипировка'),('notWearing','Без экипировки')]:
            item_ids=ids(source.get(field,[]))
            if item_ids:labels.append(label+': '+', '.join(by_id[i]['name_ru'] for i in item_ids if i in by_id))
            if field=='containsAll':value['items'].extend(i for i in item_ids if i not in value['items'])
        if (source.get('distance') or {}).get('value'):labels.append('Дистанция: '+source['distance'].get('compareMethod','')+' '+str(source['distance']['value'])+' м')
        if source.get('timeFromHour') or source.get('timeUntilHour'):labels.append(f"Время: {int(source.get('timeFromHour') or 0):02}:00–{int(source.get('timeUntilHour') or 0):02}:00")
        if source.get('dogTagLevel'):labels.append('Минимальный уровень жетона: '+str(source['dogTagLevel']))
        if (source.get('minDurability') or 0)>0:labels.append('Прочность не ниже '+str(source['minDurability'])+'%')
        if (source.get('maxDurability') if source.get('maxDurability') is not None else 100)<100:labels.append('Прочность не выше '+str(source['maxDurability'])+'%')
        if source.get('bodyParts'):labels.append('Части тела: '+', '.join(text(part,'ru') for part in source['bodyParts']))
        value['conditions_ru']=labels
        return value
    result=[]
    regular=read('regular-tasks').get('data',{}).get('tasks',{})
    combined={**regular,**tasks.get('tasks',{})}
    for source in combined.values():
        value=copy.deepcopy(source);value['kind']='side'
        value['modes']=([mode] if source['id'] in tasks.get('tasks',{}) else [])+(['regular'] if source['id'] in regular else [])
        value['name_en']=text(source['name'],'en');value['name_ru']=text(source['name'],'ru')
        value['name']=value['name_en'];value['objectives']=[objective(o) for o in source.get('objectives',[])]
        trader=traders.get(source.get('trader'),{})
        value['trader_name']=text(trader.get('name',source.get('trader','')),'ru')
        value['trader_image']=trader.get('imageLink','')
        for req in value.get('traderRequirements',[]):
            req['trader_name']=text(traders.get(req.get('trader'),{}).get('name',req.get('trader','')),'ru')
        for req in value.get('otherRequirements',[]):
            if req.get('type')=='dialogue':
                req['label']='Диалог: '+', '.join(text(traders.get(i,{}).get('name',i),'ru') for i in req.get('traders',[]))
            else:req['label']=text(req.get('id',''),'ru','Условие сюжетного прогресса')+' '+str(req.get('compareMethod',''))+' '+str(req.get('value',''))
        map_value=maps.get('maps',{}).get(source.get('map'),{}) if isinstance(maps.get('maps'),dict) else {}
        value['map_name']=text(map_value.get('name',source.get('map') or ''),'ru','Любая локация')
        value['source']=BASE+mode+'/tasks'
        result.append(value)
    story=read('storymaps')
    for chapter in story.get('story',{}).get('chapters',[]):
        value={'id':'story:'+chapter['id'],'name':chapter['name'],'name_en':chapter['name'],
            'name_ru':text(chapter.get('questId','')+' name','ru',chapter['name']), 'kind':'story',
            'objectives':[],'taskRequirements':[{'task':'story:'+k,'status':['complete']} for k in chapter.get('requires',[])],
            'trader_name':'История','map_name':'Несколько локаций','minPlayerLevel':0,
            'wikiLink':chapter.get('wikiLink'),'source':STORY,'order':chapter.get('order',0)}
        for raw in chapter.get('objectives',[]):
            o=objective({'id':raw['id'],'description':raw['id'],'optional':raw['type']!='main',
                         'type':'story','count':1,'items':[]})
            o['description_en']=raw['description'];o['description_ru']=text(raw['id'],'ru',raw['description'])
            o['needs']=raw.get('needs',[]);o['indent']=raw.get('indent',0)
            desc=raw['description'].lower()
            ru_desc=o['description_ru'].casefold()
            currency='Roubles' if 'rub' in desc or 'рубл' in ru_desc else 'Dollars' if 'usd' in desc or 'доллар' in ru_desc else 'Euros' if 'eur' in desc or 'евро' in ru_desc else None
            if currency and ('collect' in desc or 'hand over' in desc):
                item=next((v for v in catalog if v['name']==currency),None)
                if item:o['items']=[item['id']];o['type']='giveItem' if 'hand over' in desc else 'findItem'
            needs=raw.get('needs','');needs=needs if isinstance(needs,str) else ', '.join(needs)
            words=re.sub(r'[^a-z0-9]+',' ',needs.casefold())
            for name,item in (named_catalog if words else []):
                if len(name)>=6 and name in words and item['id'] not in o['items']:
                    o['items'].append(item['id']);o['type']='useItem'
            # This public chapter's flash drive is a distinct quest object, not the barter USB stick.
            if chapter['id']=='falling-skies' and ('G-Wagon' in raw['description'] or raw['id']=='678f6ec00199b227bbf61473') and 'flash drive' in desc:
                item=next((v for v in catalog if v['name']=='G-Wagon flash drive'),None)
                if item:o['items']=[item['id']];o['type']='giveQuestItem' if 'hand over' in desc else 'findQuestItem'
            value['objectives'].append(o)
        result.append(value)
    hideout=[];raw_stations=data('hideout')
    for source in raw_stations.values():
        levels=[]
        for raw in source.get('levels',[]):
            levels.append({'level':raw['level'],'requirements':[{'name':text(raw_stations[r['station']]['name'],'en'),'level':r['level']} for r in raw.get('stationLevelRequirements',[]) if r['station'] in raw_stations]})
        hideout.append({'name':text(source['name'],'en'),'levels':levels})
    return {'tasks':result,'items':catalog,'hideout_dependencies':hideout,'source':BASE+mode+'/tasks',
            'story_source':STORY,'updated':time.time(),'mode':mode,'quest_item_ids':list(tasks.get('questItems',{}))}

if __name__=='__main__':
    p=Path('data/api');download(p);save_json(Path('data/progression.json'),normalize(p))
