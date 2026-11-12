"""Whole-catalog visual retrieval. Public artwork only; no game data access."""
from __future__ import annotations

import hashlib
import json
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from io import BytesIO
from pathlib import Path

import cv2
import numpy as np
import requests
from PIL import Image

from .catalog import item_records
from .core import save_json


def descriptor(image):
    if image.ndim == 2:
        gray = image
    else:
        gray = cv2.cvtColor(image[:, :, :3], cv2.COLOR_BGR2GRAY)
    h, w = gray.shape
    dx, dy = max(1, round(w*.12)), max(1, round(min(h, 64)*.24))
    center = gray[dy:max(dy+1,h-dy), dx:max(dx+1,w-dx)]
    small = cv2.resize(center, (32, 32)).astype(np.float32)
    small = (small-small.mean())/max(8., float(small.std()))
    dct = cv2.dct(small)[:8,:8].ravel()[1:]
    dct /= max(1e-6, np.linalg.norm(dct))
    spatial = cv2.resize(small, (8, 8)).ravel()
    spatial /= max(1e-6, np.linalg.norm(spatial))
    vector = np.concatenate((dct*.75, spatial*.66))
    return vector / max(1e-6, np.linalg.norm(vector))


class VisualLibrary:
    def __init__(self, directory: Path):
        self.directory = directory
        self.lock = threading.RLock()
        self.names, self.paths, self.dimensions = [], [], []
        self.vectors = np.empty((0, 127), dtype=np.float32)
        self.status = {'running': False, 'total': 0, 'ready': 0, 'failed': 0, 'indexed': 0, 'errors': []}
        self.load()

    def load(self):
        path = self.directory / 'visual-index.npz'
        if not path.exists():
            return
        try:
            with np.load(path, allow_pickle=False) as data:
                self.names = data['names'].tolist()
                self.paths = data['paths'].tolist()
                self.dimensions = data['dimensions'].tolist()
                self.vectors = data['vectors'].astype(np.float32)
            relocated={}
            for old in set(self.paths):
                candidate=Path(old)
                if not candidate.exists():
                    candidate=next((self.directory/folder/Path(old).name for folder in ('library','grids') if (self.directory/folder/Path(old).name).is_file()),candidate)
                relocated[old]=str(candidate)
            self.paths=[relocated[path] for path in self.paths]
            self.status['indexed'] = len(set(self.names))
            self.status['ready'] = self.status['indexed']
        except (ValueError, OSError, KeyError):
            pass

    def prepare(self, catalog, progress=None, stop=None):
        records = item_records(catalog)
        total = len(records)
        self.status.update(running=True, total=total, ready=0, failed=0, errors=[])
        templates = dict(catalog.get('grid_templates', {}))
        def download(pair):
            name, item = pair
            filename = hashlib.sha256(item['id'].encode()).hexdigest()[:24]+'.png'
            path = self.directory / 'library' / filename
            previous = self.directory / 'grids' / (item['id']+'.png')
            if previous.is_file():
                return name, str(previous.resolve()), None
            if path.is_file():
                return name, str(path.resolve()), None
            if stop and stop.is_set():
                return name, None, 'Остановлено'
            try:
                url = item.get('grid_url') or item.get('icon_url')
                if not url:
                    raise ValueError('Нет публичного изображения')
                response = requests.get(url, timeout=(8, 20))
                response.raise_for_status()
                with Image.open(BytesIO(response.content)) as image:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    image.convert('RGBA').save(path)
                return name, str(path.resolve()), None
            except Exception as exc:
                return name, None, str(exc)
        try:
            with ThreadPoolExecutor(max_workers=8) as pool:
                futures = [pool.submit(download, pair) for pair in records.items()]
                for future in as_completed(futures):
                    name, path, error = future.result()
                    if path:
                        templates[name] = path
                        self.status['ready'] += 1
                    else:
                        self.status['failed'] += 1
                        self.status['errors'].append({'name': name, 'error': error})
                    if progress:
                        progress(dict(self.status))
                    if stop and stop.is_set():
                        for pending in futures:
                            pending.cancel()
                        break
            self.build(templates)
            save_json(self.directory / 'library-status.json', self.status)
            return templates
        finally:
            self.status['running'] = False

    def build(self, templates):
        names, paths, dimensions, vectors = [], [], [], []
        for name, path in templates.items():
            image = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)
            if image is None:
                continue
            for rotation in range(4):
                rotated = np.ascontiguousarray(np.rot90(image, rotation))
                names.append(name)
                paths.append(path)
                dimensions.append((rotated.shape[1], rotated.shape[0]))
                vectors.append(descriptor(rotated))
        matrix = np.asarray(vectors, dtype=np.float32).reshape((-1, 127))
        with self.lock:
            self.names, self.paths, self.dimensions, self.vectors = names, paths, dimensions, matrix
            self.status['indexed'] = len(set(names))
        self.directory.mkdir(parents=True, exist_ok=True)
        temporary = self.directory / 'visual-index.tmp.npz'
        np.savez_compressed(temporary, names=np.asarray(names), paths=np.asarray(paths),
                            dimensions=np.asarray(dimensions), vectors=matrix)
        temporary.replace(self.directory / 'visual-index.npz')

    @property
    def footprints(self):
        with self.lock:
            return {(max(1,round(w/64)), max(1,round(h/64))) for w,h in self.dimensions}

    def retrieve(self, image, limit=16):
        return self.retrieve_many([image],limit)[0]

    def retrieve_many(self, images, limit=16):
        with self.lock:
            if not len(self.names):
                return [{} for _ in images]
            if not images:
                return []
            grays=[cv2.cvtColor(image,cv2.COLOR_RGB2GRAY) if image.ndim==3 else image for image in images]
            vectors=np.stack([descriptor(gray) for gray in grays])
            if not hasattr(self,'dimension_cache') or self.dimension_cache[0]!=id(self.dimensions):
                self.dimension_cache=(id(self.dimensions),np.asarray(self.dimensions))
            dims=self.dimension_cache[1]
            ratios=[gray.shape[1]/gray.shape[0] for gray in grays]
            eligible=np.arange(len(self.names))
            if len(set(ratios))==1:
                eligible=np.flatnonzero(np.abs((dims[:,0]/dims[:,1])/ratios[0]-1)<=.23)
                if not len(eligible):return [{} for _ in images]
            similarities=(self.vectors if len(eligible)==len(self.names) else self.vectors[eligible]) @ vectors.T
            dims=dims[eligible]
            results=[]
            for column,gray in enumerate(grays):
                ratio=gray.shape[1]/gray.shape[0]
                scores=np.where(np.abs((dims[:,0]/dims[:,1])/ratio-1)<=.23,similarities[:,column],-2)
                count=min(len(scores),limit*4)
                indexes=np.argpartition(scores,-count)[-count:]
                result={}
                for local_index in indexes[np.argsort(scores[indexes])[::-1]]:
                    if scores[local_index]<.15:
                        break
                    index=int(eligible[local_index])
                    name=self.names[index]
                    if name in result:
                        continue
                    result[name]={'path':self.paths[index],'rotation':int(index%4),'coarse_score':float(scores[local_index])}
                    if len(result)>=limit:
                        break
                results.append(result)
            return results


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--data', default='data')
    options = parser.parse_args()
    directory = Path(options.data)
    source = json.loads((directory / 'catalog.json').read_text(encoding='utf-8'))
    library = VisualLibrary(directory)
    last = [-1]
    def progress(status):
        done = status['ready']+status['failed']
        if done//250 != last[0]:
            last[0] = done//250
            print(f"{done}/{status['total']}; failed={status['failed']}", flush=True)
    paths = library.prepare(source, progress)
    save_json(directory / 'all-templates.json', paths)
    print(json.dumps(library.status, ensure_ascii=False), flush=True)
