from __future__ import annotations

import json
import hashlib
import io
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

STATIC = Path(__file__).parent / 'web'


class LocalWeb:
    def __init__(self, service, command, port=8765):
        self.service, self.command = service, command
        self.token = secrets.token_urlsafe(32)
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def send(self, payload, content='application/json; charset=utf-8', status=200):
                if not isinstance(payload, bytes):
                    payload = json.dumps(payload, ensure_ascii=False).encode('utf-8')
                self.send_response(status)
                self.send_header('Content-Type', content)
                self.send_header('Content-Length', str(len(payload)))
                self.send_header('Cache-Control', 'no-store')
                self.send_header('X-Content-Type-Options', 'nosniff')
                self.send_header('Referrer-Policy', 'no-referrer')
                self.send_header('Content-Security-Policy', "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'")
                self.end_headers()
                self.wfile.write(payload)

            def allowed(self):
                return self.headers.get('Host') == f'127.0.0.1:{owner.server.server_port}'

            def do_GET(self):
                if not self.allowed():
                    return self.send({'error': 'Invalid host'}, status=403)
                parsed = urlparse(self.path)
                query = parse_qs(parsed.query)
                if parsed.path == '/api/state':
                    return self.send({**owner.service.snapshot(), 'token': owner.token})
                if parsed.path == '/api/items':
                    try:return self.send(owner.service.search(query.get('q',[''])[0],int(query.get('limit',['48'])[0]),int(query.get('page',['1'])[0]),query.get('category',[''])[0],query.get('type',[''])[0],query.get('sort',['name'])[0],query.get('tracked',['0'])[0]=='1'))
                    except (ValueError,TypeError):return self.send({'error':'Некорректный фильтр'},status=400)
                if parsed.path == '/api/quests':
                    try:return self.send(owner.service.quests(query.get('q',[''])[0],query.get('kind',['side'])[0],query.get('status',[''])[0],query.get('trader',[''])[0],int(query.get('page',['1'])[0]),mode=query.get('mode',[''])[0]))
                    except ValueError:return self.send({'error':'Некорректный фильтр'},status=400)
                if parsed.path == '/api/quest':
                    try:return self.send(owner.service.quest(query.get('id',[''])[0]))
                    except ValueError:return self.send({'error':'Квест не найден'},status=404)
                if parsed.path == '/api/portrait':
                    trader=query.get('id',[''])[0]
                    task=next((q for q in owner.service.quest_progress.tasks.values() if q.get('trader')==trader),{})
                    url=task.get('trader_image','');cache=owner.service.directory/'portraits'/(hashlib.sha256(trader.encode()).hexdigest()+'.png')
                    if cache.is_file():return self.send(cache.read_bytes(),'image/png')
                    if urlparse(url).hostname=='assets.tarkov.dev':
                        try:
                            import requests
                            from PIL import Image
                            r=requests.get(url,timeout=12);r.raise_for_status()
                            with Image.open(io.BytesIO(r.content)) as img:
                                img.thumbnail((100,100));buffer=io.BytesIO();img.convert('RGBA').save(buffer,'PNG')
                            cache.parent.mkdir(parents=True,exist_ok=True);cache.write_bytes(buffer.getvalue());return self.send(buffer.getvalue(),'image/png')
                        except Exception:pass
                    return self.send((STATIC/'item.svg').read_bytes(),'image/svg+xml')
                if parsed.path == '/api/frame':
                    kind = query.get('kind', ['loot'])[0]
                    with owner.service.lock:
                        frame = owner.service.frames.get(kind)
                    return self.send(frame, 'image/jpeg') if frame else self.send({'error': 'Нет кадра'}, status=404)
                if parsed.path == '/api/setup/frame':
                    with owner.service.lock:
                        frame=owner.service.setup_image
                    return self.send(frame,'image/png') if frame else self.send({'error':'Сначала нажмите F6 над игрой'},status=404)
                if parsed.path in ('/api/icon', '/api/grid'):
                    grid = parsed.path == '/api/grid'
                    name = query.get('name', [''])[0]
                    with owner.service.lock:
                        path = owner.service.catalog.get('grid_templates', {}).get(name)
                        if not grid:
                            path = path or owner.service.catalog.get('icons', {}).get(name)
                    if path and Path(path).is_file():
                        return self.send(Path(path).read_bytes(), 'image/png')
                    cache = owner.service.directory / ('card-grids' if grid else 'thumbnails') / (hashlib.sha256(name.encode()).hexdigest()[:24] + '.png')
                    if cache.is_file():
                        return self.send(cache.read_bytes(), 'image/png')
                    with owner.service.lock:
                        url = owner.service.records.get(name, {}).get('grid_url' if grid else 'icon_url', '')
                    if urlparse(url).hostname == 'assets.tarkov.dev':
                        try:
                            from PIL import Image
                            import requests
                            response = requests.get(url, timeout=10)
                            response.raise_for_status()
                            with Image.open(io.BytesIO(response.content)) as image:
                                if not grid:
                                    image.thumbnail((96, 96))
                                buffer = io.BytesIO()
                                image.convert('RGBA').save(buffer, 'PNG')
                            cache.parent.mkdir(parents=True, exist_ok=True)
                            cache.write_bytes(buffer.getvalue())
                            return self.send(buffer.getvalue(), 'image/png')
                        except Exception:
                            pass
                    return self.send((STATIC / 'item.svg').read_bytes(), 'image/svg+xml')
                assets = {'hideout-reference.json': 'application/json; charset=utf-8',
                          'hideout-details.json': 'application/json; charset=utf-8',
                          'story-falling-skies.jpg':'image/jpeg',
                          'Bender.woff2': 'font/woff2', 'Bender-Bold.woff2': 'font/woff2'}
                if parsed.path.startswith('/assets/'):
                    name = parsed.path.removeprefix('/assets/')
                    if name in assets:
                        return self.send((STATIC / 'assets' / name).read_bytes(), assets[name])
                    return self.send({'error': 'Not found'}, status=404)
                files = {'/': 'index.html', '/app.js': 'app.js', '/style.css': 'style.css',
                         '/hideout.js': 'hideout.js', '/hideout.css': 'hideout.css',
                         '/controls.js':'controls.js','/controls.css':'controls.css','/quests.js':'quests.js','/quests.css':'quests.css'}
                if parsed.path in files:
                    name = files[parsed.path]
                    content = {'html': 'text/html; charset=utf-8', 'js': 'text/javascript; charset=utf-8', 'css': 'text/css; charset=utf-8'}[name.rsplit('.', 1)[1]]
                    return self.send((STATIC / name).read_bytes(), content)
                return self.send({'error': 'Not found'}, status=404)

            def do_POST(self):
                if not self.allowed() or self.headers.get('X-ItemSniper-Token') != owner.token or self.headers.get('Origin', owner.url) != owner.url:
                    return self.send({'error': 'Недопустимый источник запроса'}, status=403)
                try:
                    length = int(self.headers.get('Content-Length', 0))
                    if not 0 < length <= 2_000_000:
                        raise ValueError('Недопустимый размер запроса')
                    data = json.loads(self.rfile.read(length))
                    if self.path == '/api/levels':
                        owner.service.edit_levels(data['levels'])
                    elif self.path == '/api/target':
                        owner.service.edit_target(data['name'], data['count'], data['fir'])
                    elif self.path == '/api/settings':
                        owner.service.settings(data)
                    elif self.path == '/api/inventory':
                        owner.service.edit_inventory(data['slot'], data['items'],data.get('scope'))
                    elif self.path == '/api/quest':
                        owner.service.edit_quest(data['id'],data.get('status'),data.get('objectives'))
                    elif self.path == '/api/region':
                        owner.service.set_region(data['kind'],data['rectangle'])
                    elif self.path == '/api/wiki-html':
                        if not isinstance(data.get('html'),str) or not data['html'].strip():
                            raise ValueError('Нужен текст HTML-файла')
                        owner.command({'action':'import_html','html':data['html']})
                    elif self.path == '/api/inventory/delete':
                        with owner.service.lock:
                            owner.service.state.value['inventory'].pop(data['slot'], None)
                            owner.service.state.value['snapshot_scopes'].pop(data['slot'],None)
                            owner.service.changed()
                    elif self.path == '/api/action':
                        if data['action'] not in {'toggle', 'publish', 'hideout', 'inventory', 'dictionary', 'wiki', 'import_html', 'templates', 'region:hideout', 'region:inventory', 'region:loot', 'region:fir',
                            'capture_setup','capture_delayed','reset_raid','shutdown','quests_scan','stash_start','stash_finish','stash_toggle','clear_calibration','clear_logs','progression'}:
                            raise ValueError('Неизвестная команда')
                        owner.command(data['action'])
                    else:
                        return self.send({'error': 'Not found'}, status=404)
                    return self.send({'ok': True})
                except (ValueError, KeyError, TypeError, AttributeError) as exc:
                    return self.send({'error': str(exc)}, status=400)
                except Exception:
                    return self.send({'error': 'Ошибка сохранения. Проверьте доступ к папке data.'}, status=500)

        try:
            self.server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
        except OSError:
            if port == 0:
                raise
            self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.url = f'http://127.0.0.1:{self.server.server_port}'
        self.server.daemon_threads = True
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()
