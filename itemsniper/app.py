from __future__ import annotations
import ctypes
import io
import logging
from logging.handlers import RotatingFileHandler
import queue
import threading
import time
import tkinter as tk
import webbrowser
from pathlib import Path
from PIL import ImageDraw
from .catalog import load_public_dictionary
from .core import save_json
from .library import VisualLibrary
from .overlay import ScreenOverlay,annotation
from .realtime import RealtimeVision
from .service import Service
from .vision import Vision,capture
from .webserver import LocalWeb
from .wiki import import_wiki
from .automatic import TarkovWindow,AutoCalibration,SceneDetector,automatic_regions
from .questscan import parse_quests
from .paths import data_directory,bootstrap
from .live import LiveScreen
from .containers import detect_containers,visible_contents,ContainerRegistry,intersection
from .reveal import RevealLane,inventory_visible

DATA=data_directory()

class App:
    def __init__(self,root,directory=DATA,open_browser=True):
        self.root=root;root.withdraw();bootstrap(directory)
        self.service=Service(directory)
        self.vision=Vision();self.library=VisualLibrary(directory)
        self.library.status['total']=len(self.service.records);self.service.library_status=self.library.status
        self.vision.library=self.library;self.realtime=RealtimeVision(self.library)
        self.window=TarkovWindow();self.auto=AutoCalibration(directory/'autocalibration.json');self.scene=SceneDetector()
        self.service.calibration=self.auto.entries
        self.overlay=ScreenOverlay(root);self.events=queue.Queue();self.busy=False;self.deferred=[]
        self.closing=threading.Event();self.library_thread=None;self.last_overlay_at=0;self.last_story=0
        self.requested_scan=None
        self.containers=ContainerRegistry();self.live=LiveScreen(self.window,lambda:self.service.scanning);self.live_sequence=0
        self.reveal=RevealLane(self.live,self.library,lambda:self.service.catalog,lambda:self.service.scanning,lambda stats:self.events.put(('reveal_stats',stats)))
        self.realtime.urgent=lambda:bool(self.reveal.detector.queue or self.reveal.caption_jobs or self.reveal.grid_images)
        self.region_map={};self.service.live_publish=self.live_loot
        self.web=LocalWeb(self.service,lambda action:self.events.put(('command',action)))
        root.after(16,self.poll);root.after(200,self.tick)
        threading.Thread(target=self.hotkeys,daemon=True).start()
        if open_browser:root.after(250,lambda:webbrowser.open(self.web.url))
        if not self.service.catalog.get('items'):root.after(500,lambda:self.command('dictionary'))
        elif self.library.status['indexed']<len(self.service.records):root.after(800,self.prepare_library)

    def close(self):
        if self.closing.is_set():return
        self.closing.set();self.service.scanning=False;self.reveal.close();self.live.close();self.realtime.close();self.overlay.close();self.web.close();self.root.quit()

    def live_loot(self):
        frame=self.live.output
        if frame is None or not self.window.current().get('focused'):return None
        window=frame['window'];regions=self.region_map or automatic_regions(window,'inventory')
        hits=[]
        for hit in frame['hits']:
            x,y,w,h=hit['box'];cx=x+w/2+window['left'];cy=y+h/2+window['top']
            if any(key not in ('inventory','stash') and region['left']<=cx<region['left']+region['width'] and region['top']<=cy<region['top']+region['height'] for key,region in regions.items()):hits.append(hit)
        return hits

    def hotkeys(self):
        if not hasattr(ctypes,'windll'):return
        from ctypes import wintypes
        u=ctypes.windll.user32
        keys={1:('quests_scan',0x75),2:('toggle',0x76),3:('hideout',0x77),4:('stash_toggle',0x78),5:('publish',0x79)}
        registered=set();failed=set()
        msg=wintypes.MSG()
        while not self.closing.wait(.03):
            focused=self.window.current().get('focused',False)
            if focused:
                for key,(action,vk) in keys.items():
                    if key in registered or key in failed:continue
                    if u.RegisterHotKey(None,key,0x4000,vk):registered.add(key)
                    else:failed.add(key);self.events.put(('status','Бинд занят: '+action+'. Используйте кнопку в webUI.'))
            elif registered or failed:
                for key in registered:u.UnregisterHotKey(None,key)
                registered.clear();failed.clear()
            while u.PeekMessageW(ctypes.byref(msg),None,0x0312,0x0312,1):
                if focused and msg.wParam in keys:self.events.put(('command',keys[msg.wParam][0]))
        for key in registered:u.UnregisterHotKey(None,key)

    def background(self,job,callback,status=None):
        if self.busy:return False
        self.busy=True
        if status:self.service.status=status
        def worker():
            try:self.events.put(('done',callback,job()))
            except Exception as exc:
                logging.exception('Background operation failed');self.events.put(('error',str(exc)))
        threading.Thread(target=worker,daemon=True).start();return True

    def prepare_library(self):
        if self.library_thread and self.library_thread.is_alive():return
        catalog=self.service.catalog
        if not catalog.get('items'):return
        def worker():
            try:self.events.put(('library_done',self.library.prepare(catalog,stop=self.closing)))
            except Exception as exc:self.events.put(('status','Ошибка загрузки библиотеки: '+str(exc)))
        self.library_thread=threading.Thread(target=worker,daemon=True);self.library_thread.start()

    def command(self,command):
        payload=command if isinstance(command,dict) else {'action':command};action=payload['action']
        try:
            if action=='shutdown':return self.close()
            if action=='publish':self.service.publish();return
            if action=='toggle':
                self.service.scanning=not self.service.scanning
                self.service.set_health('waiting' if self.service.scanning else 'stopped','Ожидание окна Tarkov' if self.service.scanning else 'Сканер остановлен')
                if not self.service.scanning:self.overlay.hide()
                return
            if action in ('quests_scan','hideout'):
                self.requested_scan=action;self.service.status='Вернитесь в окно Tarkov: чтение начнётся автоматически.';return
            if action in ('inventory','stash_toggle','stash_start','stash_finish'):
                finish=action=='stash_finish' or action in ('inventory','stash_toggle') and self.service.stash.active
                if finish:
                    self.service.inventory_candidate=self.service.stash.finish();self.service.status='Скан схрона завершён. Проверьте и сохраните снимок в webUI.'
                else:
                    self.service.stash.start();self.service.status='Откройте схрон в Tarkov и прокручивайте плавно. F9 завершает сбор.'
                return
            if action in ('clear_calibration','clear_logs'):
                self.auto.clear();self.service.calibration={};self.scene=SceneDetector();self.realtime.fast.frame_cache.clear();self.realtime.narrow.frame_cache.clear()
                if action=='clear_logs':
                    for path in (self.service.directory/'logs').glob('*.log*'):
                        try:path.write_bytes(b'')
                        except OSError:pass
                self.service.status='Калибровка очищена. Размеры будут определены заново при следующем открытии инвентаря.';return
            if action=='templates':return self.prepare_library()
            if self.busy:self.deferred.append(payload);return
            if action=='dictionary':
                def done(catalog):self.service.set_catalog(catalog);self.prepare_library()
                self.background(load_public_dictionary,done,'Обновление справочника…')
            elif action=='progression':
                def job():
                    from .publicdata import download,normalize
                    directory=self.service.directory/'api';download(directory,refresh=True);value=normalize(directory);save_json(self.service.directory/'progression.json',value);return value
                def done(value):
                    self.service.set_progression(value);self.prepare_library();self.service.status='Квесты и зависимости обновлены.'
                self.background(job,done)
            elif action in ('wiki','import_html'):
                def job():
                    path=None
                    if payload.get('html'):
                        path=self.service.directory/'imports'/'hideout.html';path.parent.mkdir(parents=True,exist_ok=True);path.write_text(payload['html'],encoding='utf8')
                    return import_wiki(self.service.directory/'wiki-import',path)
                self.background(job,lambda catalog:self.service.set_catalog(catalog),'Импорт требований вики…')
        except Exception as exc:self.service.status=str(exc);self.service.set_health('error',str(exc))

    def poll(self):
        try:
            while True:
                event=self.events.get_nowait()
                if event[0]=='done':
                    self.busy=False
                    try:event[1](event[2])
                    except Exception as exc:logging.exception('Result failed');self.service.set_health('error',str(exc))
                elif event[0]=='library_done':
                    with self.service.lock:self.service.catalog={**self.service.catalog,'grid_templates':event[1]};save_json(self.service.directory/'catalog.json',self.service.catalog)
                elif event[0]=='error':
                    self.busy=False;self.service.scanning=False;self.overlay.hide();self.service.set_health('error',event[1]);self.service.status=event[1]
                elif event[0]=='status':self.service.status=event[1]
                elif event[0]=='command':self.command(event[1])
                elif event[0]=='reveal_stats':
                    self.service.reveal_stats=event[1]
                    if self.service.scanning and self.window.current().get('focused'):self.service.set_health('running','Распознавание новых предметов')
        except queue.Empty:pass
        if self.closing.is_set():return
        if not self.service.scanning or not self.window.current().get('focused'):
            self.overlay.hide();self.service.live_stats={}
        elif self.live.output and (self.live.output['sequence'],self.live.output.get('revision',0))!=self.live_sequence:
            frame=self.live.output;self.live_sequence=(frame['sequence'],frame.get('revision',0))
            self.service.live_stats={k:frame[k] for k in ('fps','frame_ms','sequence','backend')}
            settings=self.service.state.value
            hits=self.service.classify(frame['hits'])
            annotations=[annotation(hit,frame['window'],self.service.records.get(hit['name'],{}),settings) for hit in hits]
            self.overlay.show(annotations,frame['bounds'])
        if self.live.error:self.service.set_health('error','Захват экрана: '+self.live.error)
        if self.reveal.error:self.service.set_health('error','Распознавание новых предметов: '+self.reveal.error)
        if not self.busy and self.deferred:self.command(self.deferred.pop(0))
        self.root.after(8,self.poll)

    def tick(self):
        if self.closing.is_set():return
        window=self.window.current()
        if not self.service.scanning:
            if self.service.health['phase']!='error':self.service.set_health('stopped','Сканер остановлен')
        elif not window.get('focused'):
            self.service.set_health('waiting','Ожидание фокуса окна Tarkov' if window.get('found') else 'Ожидание запуска Escape from Tarkov')
            self.overlay.hide()
        elif not self.busy:
            catalog=self.service.catalog;settings=dict(self.service.state.value);requested=self.requested_scan
            if requested:self.requested_scan=None
            if not self.overlay.excluded_from_capture:self.overlay.hide()
            def job():
                start=time.time();snapshot=self.live.snapshot()
                if snapshot is None:return {'scene':'unknown'}
                image=snapshot['image'];captured_window=snapshot['window']
                if any(captured_window[k]!=window[k] for k in ('left','top','width','height')):return {'scene':'unknown'}
                panels=detect_containers(image)
                scene='containers' if panels else self.scene.detect(image,self.vision)
                if requested=='hideout':return {'hideout':self.vision.hideout(image,catalog),'scene':scene}
                if requested=='quests_scan' or scene=='quests' and time.monotonic()-self.last_story>2:
                    self.last_story=time.monotonic();lines=self.vision.text(image);parsed=parse_quests(image,lines,list(self.service.quest_progress.tasks.values()))
                    if requested or parsed.get('story'):return {'quests':parsed,'scene':'quests'}
                if scene not in ('stash','inventory','containers'):return {'scene':scene}
                calibration=self.auto.resolve(image,window,scene);cell=round(calibration['cell']);regions=automatic_regions(window,scene,calibration)
                results={};frames={};analyses={};stash_image=None;stash_views=[];physical=[]
                views=[]
                if panels:
                    regions={}
                    for kind,panel,crop,occluded in self.containers.identify(visible_contents(image,panels)):
                        x,y,w,h=panel['content'];region={'left':window['left']+x,'top':window['top']+y,'width':w,'height':h}
                        regions[kind]=region;views.append((kind,region,crop,64,occluded))
                else:
                    for kind,region in regions.items():
                        x,y=region['left']-window['left'],region['top']-window['top']
                        views.append((kind,region,image.crop((x,y,x+region['width'],y+region['height'])),cell,[]))
                # Loot first: a large character panel must not delay a newly revealed item.
                views.sort(key=lambda v:v[0]=='inventory')
                self.region_map=regions
                for kind,region,crop,view_cell,occluded in views:
                    x,y=region['left']-window['left'],region['top']-window['top']
                    hits=self.realtime.scan(crop,catalog,.88,view_cell,view_key=kind)
                    hits=[hit for hit in hits if not any(intersection(hit['box'],mask)[2]*intersection(hit['box'],mask)[3]>0 for mask in occluded)]
                    if kind=='stash' or kind.startswith('container:'):stash_views.append((kind,crop,hits,view_cell))
                    results[kind]=hits;analyses[kind]=dict(self.realtime.last_analysis)
                    for hit in hits:
                        X,Y,W,H=hit['box'];sx,sy=region['width']/crop.width,region['height']/crop.height
                        physical.append({**hit,'box':(round(x+X*sx),round(y+Y*sy),round(W*sx),round(H*sy))})
                    self.live.install(image,physical)
                    if kind=='stash':stash_image=crop
                    preview=crop.copy();draw=ImageDraw.Draw(preview)
                    for hit in hits:
                        X,Y,W,H=hit['box'];draw.rectangle((X,Y,X+W,Y+H),outline='#9cdc61',width=2)
                    preview.thumbnail((1200,700));buffer=io.BytesIO();preview.save(buffer,'JPEG',quality=75);frames[kind]=buffer.getvalue()
                return {'scene':scene,'results':results,'frames':frames,'analysis':analyses,'regions':regions,'elapsed':time.time()-start,'at':start,'stash_image':stash_image,'cell':cell,'stash_views':stash_views,'size':image.size,'containers':len(panels)}
            def done(result):
                if not self.window.current().get('focused'):return
                if 'hideout' in result:
                    self.service.hideout_candidate={'levels':result['hideout'][0],'raw':result['hideout'][1],'at':time.time()};self.service.status='Уровни убежища считаны: проверьте предложения в webUI.'
                elif 'quests' in result:
                    self.service.apply_quest_scan(result['quests']);self.live.clear();self.overlay.hide();self.service.set_health('running','Квесты считаны с экрана');return
                elif 'results' in result:
                    self.service.stage_scan(result['results'],result['elapsed'],result['at'],result['analysis'])
                    self.service.frames.update(result['frames']);self.service.calibration=self.auto.entries
                    if self.service.stash.begin_frame(result['size'],result['containers']):
                        for key,image,hits,cell in result['stash_views']:self.service.stash.observe_view(key,image,hits,cell)
                    self.last_overlay_at=time.time();self.service.set_health('running','Чтение схрона' if result['scene'] in ('stash','containers') else 'Распознавание предметов')
                    return
                current=self.live.snapshot()
                if current is not None and inventory_visible(current['image']):return
                self.live.clear();self.overlay.hide();self.service.set_health('waiting','Tarkov в фокусе: ожидание инвентаря или меню заданий')
            self.background(job,done)
        self.root.after(60,self.tick)

def main():
    if hasattr(ctypes,'windll'):
        try:ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except OSError:pass
    if hasattr(ctypes,'windll'):
        kernel=ctypes.windll.kernel32
        kernel.CreateMutexW.argtypes=[ctypes.c_void_p,ctypes.c_bool,ctypes.c_wchar_p]
        kernel.CreateMutexW.restype=ctypes.c_void_p
        import hashlib
        global _instance_mutex
        _instance_mutex=kernel.CreateMutexW(None,False,'Local\\SBEU-qol-sniper-'+hashlib.sha256(str(DATA.resolve()).encode()).hexdigest()[:16])
        if kernel.GetLastError()==183:
            info=DATA/'runtime.json'
            if info.exists():
                import json
                url=json.loads(info.read_text(encoding='utf8')).get('url','')
                if url.startswith('http://127.0.0.1:'):webbrowser.open(url)
            return
    bootstrap(DATA);logs=DATA/'logs';logs.mkdir(parents=True,exist_ok=True)
    logging.basicConfig(level=logging.INFO,handlers=[RotatingFileHandler(logs/'application.log',maxBytes=1000000,backupCount=3,encoding='utf8')])
    root=tk.Tk();root.withdraw();app=App(root)
    save_json(DATA/'runtime.json',{'url':app.web.url})
    try:root.mainloop()
    finally:app.close();root.destroy()
