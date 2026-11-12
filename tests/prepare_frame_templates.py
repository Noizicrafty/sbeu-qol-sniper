"""Fetch public item-art candidates for the supplied OCR captions; no screen upload."""
import difflib
import json
from pathlib import Path
from itemsniper.catalog import cache_grid_images, item_records
from itemsniper.vision import aliases
from itemsniper.core import normalized

output = Path('data/frame-validation')
catalog = json.loads(Path('data/catalog.json').read_text(encoding='utf-8'))
index = {}
for name, item in item_records(catalog).items():
    for alias in aliases(item):
        index.setdefault(alias, set()).add(name)
names = set()
names.update({'Pack of Vita juice', 'AI-2 medkit', 'Aseptic bandage', 'Army bandage', 'Iskra ration pack'})
for path in output.glob('*-ocr.json'):
    for line in json.loads(path.read_text(encoding='utf-8'))['text']:
        label = normalized(line['text']).replace('ё', 'е')
        keys = [label] if label in index else difflib.get_close_matches(label, index, n=2, cutoff=.72) if 4 <= len(label) <= 15 else []
        for key in keys:
            if len(index[key]) <= 8:
                names.update(index[key])
print('Candidates:', len(names), flush=True)
templates, errors = cache_grid_images(Path('data'), catalog, sorted(names))
catalog['grid_templates'] = templates
(output / 'catalog.json').write_text(json.dumps(catalog, ensure_ascii=False), encoding='utf-8')
print('Templates:', len(templates), 'errors:', errors, flush=True)
