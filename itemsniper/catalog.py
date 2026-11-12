"""Public, non-player item dictionary. Hideout requirements remain a separate wiki import."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .core import normalized, save_json

ITEMS_URL = 'https://api.tarkov.dev/api/v1/items'
STATIONS_URL = 'https://raw.githubusercontent.com/TarkovTracker/tarkovdata/master/hideout.json'
STATION_RU = {'Cultist Circle': 'Круг культистов', 'Defective Wall': 'Дефектная стена',
              'Gear Rack': 'Стойка снаряжения', 'Gym': 'Спортзал', 'Hall of Fame': 'Зал славы',
              'Weapon Rack': 'Оружейная стойка', 'Security': 'Безопасность'}


def public_get(url, **kwargs):
    with requests.Session() as session:
        retry = Retry(total=3, backoff_factor=.6, status_forcelist=(429, 500, 502, 503, 504))
        session.mount('https://', HTTPAdapter(max_retries=retry))
        response = session.get(url, **kwargs)
        response.raise_for_status()
        return response


def load_public_dictionary():
    def get(lang):
        response = public_get(ITEMS_URL, params={'lang': lang}, timeout=45)
        value = response.json()
        if not isinstance(value, list) or not value:
            raise ValueError('Справочник предметов недоступен')
        return value
    with ThreadPoolExecutor(max_workers=2) as pool:
        en, ru = list(pool.map(get, ('en', 'ru')))
    russian = {item['uid']: item for item in ru}
    items = []
    for source in en:
        translated = russian.get(source['uid'], {})
        name = source.get('name')
        if not name:
            continue
        items.append({'id': source['uid'], 'name': name,
                      'name_ru': translated.get('name', name),
                      'short_name': source.get('shortName', ''),
                      'short_name_ru': translated.get('shortName', ''),
                      'grid_url': source.get('img', ''), 'icon_url': source.get('icon', ''),
                      'wiki': source.get('wikiLink', ''), 'source': ITEMS_URL})
    # Only station names/translations and level numbers are used from this older dictionary.
    # Its historical material quantities / FIR rules are deliberately NOT imported.
    response = public_get(STATIONS_URL, timeout=30)
    hideout = response.json()
    stations = []
    for source in hideout['stations']:
        name = source['locales']['en']
        levels = sorted({m['level'] for m in hideout['modules'] if m['stationId'] == source['id']})
        stations.append({'name': name, 'name_ru': source['locales'].get('ru', name),
                         'levels': [{'level': level, 'items': []} for level in levels],
                         'requirements_missing': True})
    return {'items': items, 'stations': stations, 'icons': {}, 'images': {},
            'dictionary_source': ITEMS_URL, 'station_dictionary_source': STATIONS_URL,
            'dictionary_updated': datetime.now(timezone.utc).isoformat()}


def merge_catalog(existing, incoming):
    result = dict(existing)
    if incoming.get('items'):
        result['items'] = incoming['items']
    translations = {normalized(s['name']): s for s in result.get('stations', [])}
    for station in incoming.get('stations', []):
        key = normalized(station['name'])
        prior = translations.get(key)
        if prior and station.get('requirements_missing') and not prior.get('requirements_missing'):
            prior['name_ru'] = station.get('name_ru', prior.get('name_ru', prior['name']))
        else:
            value = dict(station)
            if prior:
                value.setdefault('name_ru', prior.get('name_ru', station['name']))
            translations[key] = value
    result['stations'] = list(translations.values())
    by_normalized_name = {normalized(item['name']): item['name'] for item in result.get('items', [])}
    for station in result['stations']:
        station['name_ru'] = STATION_RU.get(station['name'], station.get('name_ru', station['name']))
        for level in station['levels']:
            for item in level['items']:
                item['name'] = by_normalized_name.get(normalized(item['name']), item['name'])
    for key in ('icons', 'images'):
        result[key] = {**result.get(key, {}), **incoming.get(key, {})}
    for key in ('dictionary_source', 'station_dictionary_source', 'dictionary_updated', 'source', 'updated', 'icon_errors', 'seasonal_fir_waiver'):
        if key in incoming:
            result[key] = incoming[key]
    return result


def item_records(catalog):
    records = {}
    for source in catalog.get('items', []):
        item = dict(source)
        name = item['name']
        if name in records and records[name]['id'] != item['id']:
            item['display_name'] = name
            name = f"{name} [{item['id'][-8:]}]"
            item['name'] = name
        records[name] = item
    for station in catalog.get('stations', []):
        for level in station['levels']:
            for item in level['items']:
                records.setdefault(item['name'], {'id': item['name'], 'name': item['name'],
                                                  'name_ru': item['name'], 'wiki': item.get('wiki', '')})
    return records


def cache_grid_images(directory: Path, catalog, names):
    """Download only active templates; never downloads inspect-window images."""
    records = item_records(catalog)
    errors = []
    templates = dict(catalog.get('grid_templates', {}))
    def download(name):
        item = records.get(name, {})
        url = item.get('grid_url')
        if not url:
            # Wiki icons remain usable for small barter items, but are explicitly labelled.
            path = catalog.get('icons', {}).get(name)
            return name, path, None
        path = directory / 'grids' / (item['id'] + '.png')
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            if not path.exists():
                from io import BytesIO
                from PIL import Image
                response = requests.get(url, timeout=25)
                response.raise_for_status()
                with Image.open(BytesIO(response.content)) as image:
                    image.convert('RGBA').save(path)
            return name, str(path.resolve()), None
        except Exception as exc:
            return name, None, f'{name}: {exc}'
    with ThreadPoolExecutor(max_workers=4) as pool:
        for name, path, error in pool.map(download, names):
            if path:
                templates[name] = path
            if error:
                errors.append(error)
    return templates, errors
