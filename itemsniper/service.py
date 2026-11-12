from __future__ import annotations

import copy
import json
import threading
import time
import re
import io
from collections import Counter
from pathlib import Path

from .catalog import item_records, merge_catalog
from .core import State, save_json
from .tracking import RaidInventory, RevealQueue
from .progression import QuestProgress,resolve_hideout
from .stash import StashSession


class Service:
    def __init__(self, directory: Path):
        self.directory = directory
        self.lock = threading.RLock()
        self.state = State(directory / 'state.json')
        path = directory / 'catalog.json'
        self.catalog = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
        for mapping in ('grid_templates','icons'):
            for name,old in list(self.catalog.get(mapping,{}).items()):
                if not Path(old).is_file():
                    replacement=next((self.directory/folder/Path(old).name for folder in ('library','grids') if (self.directory/folder/Path(old).name).is_file()),None)
                    if replacement:self.catalog[mapping][name]=str(replacement.resolve())
        self.records = item_records(self.catalog)
        self.pending = {}
        self.frames = {}
        self.hideout_candidate = {'levels': {}, 'raw': '', 'at': None}
        self.inventory_candidate = {'items': {}, 'at': None}
        self.scanning = True
        self.status = 'Автоматический режим: ожидание окна Escape from Tarkov.'
        self.scan_ms = 0
        self.scan_sequence = 0
        self.dirty = True
        self.raid = RaidInventory()
        self.reveals = RevealQueue()
        self.library_status = {}
        self.setup_frame = None
        self.setup_image = None
        progression=self.directory/'progression.json'
        self.progression=json.loads(progression.read_text(encoding='utf8')) if progression.exists() else {'tasks':[],'hideout_dependencies':[]}
        self.quest_progress=QuestProgress(self.progression.get('tasks',[]),self.state.value)
        self.stash=StashSession()
        self.live_stats={}
        self.reveal_stats={}
        self.health={'phase':'waiting','message':'Ожидание окна Escape from Tarkov','at':time.time()}
        self.calibration={}
        self.quest_scan={'at':None,'quests':[],'story':None,'objectives':{}}
        if self.progression.get('items'):
            references={i['id']:i for i in self.progression['items']}
            existing=set()
            for item in self.catalog.get('items',[]):
                existing.add(item['id']);reference=references.get(item['id'])
                if reference:
                    item.update({k:reference[k] for k in ('types','categories','width','height') if k in reference})
                else:item.setdefault('types',['preset'])
            self.catalog.setdefault('items',[]).extend(i for i in references.values() if i['id'] not in existing)
            self.records=item_records(self.catalog)
            save_json(self.directory/'catalog.json',self.catalog)

    def needed(self):
        return self.state.needed(self.catalog, self.state.value['all_levels'], raid_inventory=self.raid.items)

    def set_progression(self,value):
        with self.lock:
            self.progression=value;self.quest_progress=QuestProgress(value.get('tasks',[]),self.state.value)
            existing={item['id']:item for item in self.catalog.get('items',[])}
            for reference in value.get('items',[]):
                if reference['id'] in existing:
                    existing[reference['id']].update({k:reference[k] for k in ('types','categories','width','height') if k in reference})
                else:self.catalog.setdefault('items',[]).append(reference)
            self.records=item_records(self.catalog);save_json(self.directory/'progression.json',value);save_json(self.directory/'catalog.json',self.catalog);self.changed()

    def current_targets(self):
        owned = self.state.owned(raid_inventory=self.raid.items)
        fir = self.state.owned(fir=True, raid_inventory=self.raid.items)
        result = copy.deepcopy(self.state.value['active_targets'])
        for name, need in result.items():
            need['owned'], need['fir_owned'] = owned[name], fir[name]
            need['remaining'] = max(0,need['required']-owned[name],need['fir_required']-fir[name])
        return result

    def set_catalog(self, incoming):
        with self.lock:
            self.catalog = merge_catalog(self.catalog, incoming)
            self.records = item_records(self.catalog)
            from .core import normalized
            canonical = {normalized(s['name']): s['name'] for s in self.catalog.get('stations', [])}
            self.state.value['levels'] = {canonical.get(normalized(name), name): level
                                          for name, level in self.state.value['levels'].items()}
            self.state.save()
            save_json(self.directory / 'catalog.json', self.catalog)
            self.dirty = True

    def search(self, query='', limit=60, page=1, category='', kind='', sort='name', tracked=False):
        with self.lock:
            words = query.casefold().replace('ё', 'е').split()
            results = []
            for item in self.records.values():
                haystack = ' '.join(str(item.get(k, '')) for k in ('name', 'display_name', 'name_ru', 'short_name', 'short_name_ru', 'id')).casefold().replace('ё', 'е')
                if category and not any(c.get('id')==category for c in item.get('categories',[])):continue
                if kind and kind not in item.get('types',[]):continue
                if tracked and item['name'] not in self.state.value['manual']:continue
                if all(word in haystack for word in words):
                    results.append(self.present_item(item))
            limit=max(12,min(120,int(limit)));pages=max(1,(len(results)+limit-1)//limit);page=max(1,min(pages,int(page)))
            results.sort(key=lambda v:(v['name'] if sort=='english' else v.get('name_ru',v['name'])).casefold())
            categories={c['id']:c for i in self.records.values() for c in i.get('categories',[])}
            return {'items':results[(page-1)*limit:page*limit],'total':len(results),'catalog_total':len(self.records),
                'page':page,'pages':pages,'limit':limit,'categories':sorted(categories.values(),key=lambda c:c['name']),
                'types':sorted({t for i in self.records.values() for t in i.get('types',[])})}

    def present_item(self, item):
        value = dict(item)
        name = value['name']
        value['image'] = '/api/icon?name=' + __import__('urllib.parse', fromlist=['quote']).quote(name)
        return value

    def snapshot(self):
        with self.lock:
            state = self.state.value
            needed = self.needed()
            presented_names = (set(state['manual']) | set(state['active_targets']) | set(needed)
                               | {name for snapshot in state['inventory'].values() for name in snapshot}
                               | set(self.inventory_candidate['items'])
                               | set(self.raid.items or {})
                               | {req['name'] for station in self.catalog.get('stations', [])
                                  for level in station['levels'] for req in level['items']})
            return copy.deepcopy({
                'levels': state['levels'], 'stations': self.catalog.get('stations', []),
                'manual': state['manual'], 'inventory': state['inventory'],
                'needed': needed,
                'active_targets': state['active_targets'], 'published': state['published'],
                'published_at': state['published_at'], 'regions': state['regions'],
                'settings': {key: state[key] for key in ('all_levels', 'threshold', 'slot_size', 'interval', 'hideout_fir_required',
                    'overlay_labels','overlay_outlines','protect_surplus','color_needed','color_surplus','color_uncertain','color_other')},
                'items': {name: self.present_item(self.records[name]) for name in presented_names if name in self.records},
                'hideout_candidate': self.hideout_candidate, 'inventory_candidate': self.inventory_candidate,
                'scanning': self.scanning, 'scan_ms': self.scan_ms, 'sequence': self.scan_sequence,
                'status': self.status, 'dirty': self.dirty, 'catalog_total': len(self.records),
                'pending_at': {key: value['at'] for key, value in self.pending.items()},
                'source': self.catalog.get('source'), 'updated': self.catalog.get('updated'),
                'dictionary_source': self.catalog.get('dictionary_source'),
                'template_count': len(self.catalog.get('grid_templates', {})),
                'fir_calibrated': bool(self.catalog.get('fir_template')),
                'seasonal_fir_waiver': self.catalog.get('seasonal_fir_waiver', False),
                'library': self.library_status, 'raid_inventory': self.raid.items or {},
                'raid_observed_at': self.raid.last_at, 'snapshot_scopes': state['snapshot_scopes'],
                'reveals': {kind: {'waiting': len(boxes), 'revealed': self.reveals.revealed.get(kind,0)} for kind,boxes in self.reveals.regions.items()},
                'setup_frame': self.setup_frame,
                'health':self.health,'calibration':self.calibration,'stash_scan':self.stash.snapshot(),
                'live':self.live_stats,
                'reveal':self.reveal_stats,
                'quest_progress':state['quests'],'quest_count':len(self.quest_progress.tasks),'quest_scan':self.quest_scan,
                'quest_source':self.progression.get('source'),'story_source':self.progression.get('story_source'),
                'quest_targets':self.quest_progress.targets(self.records),
            })

    def edit_levels(self, values):
        with self.lock:
            self.state.value['levels']=resolve_hideout(self.state.value['levels'],values,self.catalog.get('stations',[]),self.progression.get('hideout_dependencies',[]))
            self.changed()

    def set_health(self,phase,message):
        with self.lock:self.health={'phase':phase,'message':message,'at':time.time()}

    def quests(self,query='',kind='side',status='',trader='',page=1,limit=40,mode=''):
        with self.lock:
            rows=[]
            for q in self.quest_progress.tasks.values():
                p=self.quest_progress.value(q['id'])
                if kind and q['kind']!=kind:continue
                if mode and q['kind']=='side' and mode not in q.get('modes',['pve','regular']):continue
                if status and p.get('status')!=status:continue
                if trader and q.get('trader_name')!=trader:continue
                if query.casefold() not in (q['name_ru']+' '+q['name_en']).casefold():continue
                done=sum(bool(p.get('objectives',{}).get(o['id'],{}).get('done')) for o in q['objectives'] if not o.get('optional'))
                total=sum(not o.get('optional') for o in q['objectives'])
                rows.append({k:q.get(k) for k in ('id','name_ru','name_en','kind','trader','trader_name','trader_image','map_name','minPlayerLevel','order')}|{'status':p.get('status','locked'),'percent':round(done/max(1,total)*100)})
            rows.sort(key=lambda q:(q.get('order') or 999,q['name_ru']))
            limit=max(10,min(100,int(limit)));pages=max(1,(len(rows)+limit-1)//limit);page=max(1,min(pages,int(page)))
            return {'quests':rows[(page-1)*limit:page*limit],'total':len(rows),'page':page,'pages':pages,
                'traders':sorted({q.get('trader_name','') for q in self.quest_progress.tasks.values() if q['kind']=='side'})}

    def quest(self,qid):
        with self.lock:
            if qid not in self.quest_progress.tasks:raise ValueError('Неизвестный квест')
            q=copy.deepcopy(self.quest_progress.tasks[qid]);q['progress']=copy.deepcopy(self.quest_progress.value(qid))
            for o in q['objectives']:
                value=q['progress'].get('objectives',{}).get(o['id'],{})
                if 'optional' in value:o['optional']=value['optional']
            by_id={r['id']:self.present_item(r) for r in self.records.values()}
            q['items']={iid:by_id[iid] for o in q['objectives'] for iid in o.get('items',[]) if iid in by_id}
            q['previous']=[{'id':r['task'],'status':r.get('status',[]),'name':self.quest_progress.tasks.get(r['task'],{}).get('name_ru',r['task'])} for r in q.get('taskRequirements',[])]
            return q

    def edit_quest(self,qid,status=None,objectives=None):
        with self.lock:
            result=self.quest_progress.update(qid,status,objectives);self.changed();return result

    def apply_quest_scan(self,result):
        with self.lock:
            if result.get('story'):
                values={k:{**{key:v[key] for key in ('count','done','target')},'optional':v.get('visible_optional',False)} for k,v in result['objectives'].items()}
                self.quest_progress.update(result['story'],'active',values)
            for q in result.get('quests',[]):self.quest_progress.update(q['id'],q['status'])
            self.quest_scan={**result,'at':time.time()};self.changed()

    def edit_target(self, name, count, fir):
        with self.lock:
            if name not in self.records or type(count) is not int or not 0 <= count <= 10000000 or type(fir) is not bool:
                raise ValueError('Некорректный предмет или количество')
            if count:
                self.state.value['manual'][name] = {'count': count, 'fir': fir}
            else:
                self.state.value['manual'].pop(name, None)
            self.changed()

    def edit_inventory(self, slot, items, scope=None):
        with self.lock:
            if scope is not None and scope not in ('character','stash'):
                raise ValueError('Некорректный тип снимка')
            if not isinstance(slot, str) or not slot.strip() or len(slot) > 80:
                raise ValueError('Нужно имя снимка')
            result = {}
            for name, value in items.items():
                count, fir = value.get('count'), value.get('fir')
                if name not in self.records or type(count) is not int or type(fir) is not int or not 0 <= fir <= count <= 10000000:
                    raise ValueError('Количество FIR должно быть от нуля до общего количества')
                if count:
                    result[name] = {'count': count, 'fir': fir}
            self.state.value['inventory'][slot] = result
            if scope is not None:
                self.state.value['snapshot_scopes'][slot] = scope
            self.changed()

    def settings(self, values):
        with self.lock:
            limits = {'threshold': (.65, .99), 'slot_size': (24, 160), 'interval': (.03, 10)}
            result = {}
            for key, value in values.items():
                if key in ('all_levels', 'hideout_fir_required', 'overlay_labels', 'overlay_outlines', 'protect_surplus'):
                    if type(value) is not bool:
                        raise ValueError('Некорректный режим уровней')
                    result[key] = value
                elif key in ('color_needed','color_surplus','color_uncertain','color_other'):
                    if not isinstance(value,str) or not re.fullmatch(r'#[0-9a-fA-F]{6}',value):
                        raise ValueError('Некорректный цвет')
                    result[key] = value
                elif key in limits:
                    low, high = limits[key]
                    if type(value) not in (int, float) or not low <= value <= high:
                        raise ValueError('Параметр вне диапазона: ' + key)
                    result[key] = value
                else:
                    raise ValueError('Неизвестный параметр')
            self.state.value.update(result)
            self.changed()

    def changed(self):
        self.dirty = True
        self.state.save()

    def stage_scan(self, results, elapsed, captured_at=None, analysis=None):
        with self.lock:
            now = captured_at if captured_at is not None else time.time()
            for key in list(self.pending):
                if key.startswith('container:') and key not in results:self.pending.pop(key,None)
            for kind, hits in results.items():
                self.pending[kind] = {'hits': copy.deepcopy(hits), 'at': now, 'analysis': copy.deepcopy((analysis or {}).get(kind, {}))}
                self.reveals.observe(kind,hits,(analysis or {}).get(kind,{}))
                if kind == 'inventory':
                    self.raid.observe(hits,(analysis or {}).get(kind,{}),now)
            self.scan_ms = round(elapsed * 1000)
            self.scan_sequence += 1

    def stage_inventory(self):
        with self.lock:
            pending = self.pending.get('inventory')
            if not pending or time.time() - pending['at'] > max(10, self.scan_ms/1000*3):
                raise ValueError('Нет свежего кадра инвентаря. Включите сканер и откройте инвентарь.')
            items = {}
            for hit in pending['hits']:
                entry = items.setdefault(hit['name'], {'count': 0, 'fir': 0, 'unknown': 0})
                count = hit.get('count', 1)
                entry['count'] += count
                entry['fir'] += count if hit.get('fir') == 'yes' else 0
                entry['unknown'] += count if hit.get('fir') == 'unknown' else 0
            self.inventory_candidate = {'items': items, 'at': pending['at'], 'analysis': pending.get('analysis', {}),
                                        'warning': 'Учитываются только видимые предметы. Скрытые и необследованные области не считаются пустыми.'}

    def publish(self):
        with self.lock:
            targets = self.needed()
            self.state.value['active_targets'] = targets
            containers=[value for key,value in self.pending.items() if key.startswith('container:')]
            pending={'hits':[hit for value in containers for hit in value['hits']],'at':max(v['at'] for v in containers)} if containers else self.pending.get('loot', {})
            fresh = time.time() - pending.get('at', 0) <= max(10, self.scan_ms/1000*3)
            published = self.classify(pending.get('hits', []) if fresh else [])
            live=getattr(self,'live_publish',None)
            if live is not None:
                current=live()
                if current is not None:published=self.classify(current);fresh=True
            self.state.value['published'] = published
            self.state.value['published_at'] = time.time()
            self.state.save()
            self.dirty = False
            self.status = f'F10: список обновлён; найдено {len(published)}.' + ('' if fresh else ' Свежего кадра обыска нет.')
            return copy.deepcopy(published)

    def classify(self, hits):
        with self.lock:
            targets = self.current_targets()
            budgets = {name:[max(0,n['required']-n['owned']-max(0,n['fir_required']-n['fir_owned'])),
                            max(0,n['fir_required']-n['fir_owned'])] for name,n in targets.items()}
            result = []
            quest_targets=self.quest_progress.targets(self.records)
            for hit in sorted(hits, key=lambda h:(h.get('fir')!='yes',h['box'][1],h['box'][0])):
                name = hit.get('name','')
                need = targets.get(name)
                status, reason, take = 'other', 'Не в списке поиска', 0
                if hit.get('ambiguous'):
                    status,reason = 'uncertain','Неоднозначное распознавание'
                elif need:
                    budget = budgets[name] if self.state.value['protect_surplus'] else budgets[name].copy()
                    count = hit.get('count',1)
                    fir_take = min(count,budget[1]) if hit.get('fir')=='yes' else 0
                    normal_take = min(count-fir_take,budget[0])
                    take = fir_take+normal_take
                    budget[0] -= normal_take
                    budget[1] -= fir_take
                    if take:
                        status,reason = 'needed',f'Взять {take}'
                    elif budget[1]>0 and hit.get('fir')!='yes':
                        status,reason = 'uncertain','Нужен FIR: галочка не подтверждена'
                    else:
                        status,reason = 'surplus','Уже достаточно / излишек'
                quest_uses=[q for q in quest_targets.get(name,[]) if not q['fir'] or hit.get('fir')=='yes'] if not hit.get('ambiguous') else []
                result.append({**hit,'status':status,'eligible':status=='needed','reason':reason,'take_count':take,
                               'quest_needed':bool(quest_uses),'quest_uses':quest_uses,
                               'remaining':need['remaining'] if need else 0})
            return result

    def reset_raid(self):
        with self.lock:
            self.raid.reset()
            self.reveals = RevealQueue()
            self.pending.clear()
            self.status = 'Новый рейд: наблюдения персонажа и очередь раскрытия сброшены. Схрон сохранён.'

    def set_region(self, kind, rectangle):
        with self.lock:
            if kind not in ('hideout','inventory','loot','fir') or self.setup_frame is None:
                raise ValueError('Сначала снимите экран по F6')
            values=[rectangle.get(key) for key in ('x','y','width','height')]
            if any(type(value) is not int for value in values):
                raise ValueError('Координаты должны быть целыми числами')
            x,y,w,h=values
            bounds=self.setup_frame
            if x<0 or y<0 or w<5 or h<5 or x+w>bounds['width'] or y+h>bounds['height']:
                raise ValueError('Область выходит за границы снимка')
            if kind=='fir':
                if w>30 or h>26 or self.setup_image is None:
                    raise ValueError('Образец FIR: 5–30 × 5–26 пикселей')
                from PIL import Image
                path=self.directory/f'fir-{time.time_ns()}.png'
                path.parent.mkdir(parents=True,exist_ok=True)
                with Image.open(io.BytesIO(self.setup_image)) as image:
                    image.crop((x,y,x+w,y+h)).save(path)
                self.catalog={**self.catalog,'fir_template':str(path.resolve())}
                save_json(self.directory/'catalog.json',self.catalog)
            else:
                if w<30 or h<30:
                    raise ValueError('Минимальный размер области: 30 × 30')
                self.state.value['regions'][kind]={'left':bounds['left']+x,'top':bounds['top']+y,'width':w,'height':h}
                self.state.save()
            self.status='Область сохранена через webUI: '+kind
