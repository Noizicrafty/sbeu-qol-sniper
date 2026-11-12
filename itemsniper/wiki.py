"""Import requirements and icon URLs from the public wiki HTML, without bypassing access controls."""
from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from .core import save_json

WIKI = 'https://escapefromtarkov.fandom.com/wiki/Hideout'
SESSION = requests.Session()
SESSION.headers['User-Agent'] = 'ItemSniper/0.1 (personal screen-only hideout companion)'


def fetch(url):
    response = SESSION.get(url, timeout=30)
    response.raise_for_status()
    return response


def parse_html(html: str, source=WIKI):
    soup = BeautifulSoup(html, 'html.parser')
    stations = []
    images = {}
    for table in soup.select('table'):
        rows = table.find_all('tr', recursive=False)
        if not rows:
            body = table.find('tbody', recursive=False)
            rows = body.find_all('tr', recursive=False) if body else []
        if not rows:
            continue
        header_index = None
        for index, row in enumerate(rows[:4]):
            headers = [cell.get_text(' ', strip=True).casefold() for cell in row.find_all(['th', 'td'], recursive=False)]
            if 'level' in headers and any('requirement' in h for h in headers):
                header_index = index
                break
        if header_index is None:
            continue
        if header_index:
            title_cell = rows[0].find(['th', 'td'])
            name = next((text.strip() for text in title_cell.stripped_strings if text.strip()), '')
        else:
            heading = table.find_previous(['h2', 'h3', 'h4'])
            if not heading:
                continue
            name = heading.get_text(' ', strip=True).replace('[ edit ]', '').replace('[edit]', '').strip()
        levels = []
        requirement_column = next(i for i, h in enumerate(headers) if 'requirement' in h)
        level_column = headers.index('level')
        for row in rows[header_index+1:]:
            cells = row.find_all(['th', 'td'], recursive=False)
            if len(cells) <= max(requirement_column, level_column):
                continue
            match = re.fullmatch(r'\s*(\d+)\s*', cells[level_column].get_text(' ', strip=True))
            if not match:
                continue
            items = []
            requirements = cells[requirement_column]
            for li in requirements.find_all('li'):
                # Skip nested lists and non-item requirements such as trader/skill levels.
                if li.find('ul') or li.find('ol'):
                    continue
                label = li.get_text(' ', strip=True)
                amount = re.match(r'^([\d,]+(?: \d{3})*)\s+', label)
                if not amount:
                    continue
                links = [a for a in li.find_all('a', href=True)
                         if a.get('title') and not a.find('img') and 'found in raid' not in a.get_text().casefold()]
                if not links:
                    continue
                link = links[0]
                item_name = link.get('title', link.get_text()).strip()
                count = int(re.sub(r'\D', '', amount.group(1)))
                items.append({'name': item_name, 'count': count, 'fir': 'found in raid' in label.casefold(),
                              'wiki': urljoin(source, link['href'])})
                img = li.find('img')
                if img:
                    src = img.get('data-src') or img.get('src', '')
                    if src.startswith(('http', '//')):
                        images[item_name] = urljoin(source, src)
            levels.append({'level': int(match.group(1)), 'items': items})
        if levels:
            stations.append({'name': name, 'levels': levels})
    if not stations or not any(level['items'] for station in stations for level in station['levels']):
        raise ValueError('Таблицы требований вики не найдены. Нужен HTML самой страницы Hideout, а не страницы проверки браузера.')
    seasonal_fir_waiver = bool(re.search(r'no items required for module upgrades need to be found in raid', soup.get_text(' ', strip=True), re.I))
    return {'source': source, 'updated': datetime.now(timezone.utc).isoformat(), 'seasonal_fir_waiver': seasonal_fir_waiver,
            'stations': stations, 'images': images, 'icons': {}}


def import_wiki(directory: Path, html_path: Path | None = None):
    html = html_path.read_text(encoding='utf-8') if html_path else fetch(WIKI).text
    catalog = parse_html(html)
    icons = directory / 'icons'
    icons.mkdir(parents=True, exist_ok=True)
    errors = []
    for name, url in catalog['images'].items():
        if urlparse(url).scheme not in ('http', 'https'):
            continue
        filename = hashlib.sha256(name.encode()).hexdigest()[:20] + '.png'
        path = icons / filename
        try:
            if not path.exists():
                from PIL import Image
                from io import BytesIO
                image = Image.open(BytesIO(fetch(url).content)).convert('RGBA')
                image.save(path)
            catalog['icons'][name] = str(path.resolve())
        except Exception as exc:
            errors.append(f'{name}: {exc}')
    catalog['icon_errors'] = errors
    save_json(directory / 'catalog.json', catalog)
    return catalog
