"""Repeatable evaluation of the supplied full-HD loot frames (local files only)."""
import json
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from itemsniper.vision import Vision

output = Path('data/frame-validation')
catalog_path = output / 'catalog.json'
catalog = json.loads((catalog_path if catalog_path.exists() else Path('data/catalog.json')).read_text(encoding='utf-8'))
vision = Vision()
summaries = []
for cache in sorted(output.glob('*-ocr.json')):
    source = json.loads(cache.read_text(encoding='utf-8'))
    image = Image.open(source['file']).convert('RGB').crop(source.get('region', (1226, 48, 1919, 949)))
    lines = [(row['text'], row['score'], np.array(row['box'])) for row in source['text']]
    vision.text = lambda image, rows=lines: rows
    hits = vision.items(image, catalog)
    if cache.stem == '224755-ocr':
        from collections import Counter
        counts = Counter(hit['name'] for hit in hits)
        for name in ('Slickers chocolate bar', 'Pack of milk', 'Can of squash spread', 'Can of Max Energy energy drink'):
            assert counts[name] == 2, (name, counts[name])
        assert not any(hit['box'][1] >= 415 for hit in hits), 'Hidden lower slots must not produce items'
    if cache.stem == '224657-ocr':
        assert not any(hit['box'][1] >= 160 for hit in hits), 'Unsearched cells must not produce items'
    label = cache.stem.removesuffix('-ocr')
    summary = {'frame': label, 'analysis': vision.last_analysis,
               'hits': [{k: v for k, v in hit.items()} for hit in hits]}
    summaries.append(summary)
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype('arial.ttf', 13)
    for hit in hits:
        x, y, w, h = hit['box']
        draw.rectangle((x, y, x+w, y+h), outline='#a6ee66', width=2)
        draw.text((x, y+h-16), hit['name'][:24], font=font, fill='#ffff00', stroke_width=1, stroke_fill='black')
    image.save(output / (label + '-detections.png'))
    print(summary['frame'], [(h['name'], h['box'], h['fir']) for h in hits], vision.last_analysis, flush=True)
(output / 'results.json').write_text(json.dumps(summaries, ensure_ascii=False, indent=2), encoding='utf-8')
