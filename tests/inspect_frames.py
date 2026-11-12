"""Inspect user-supplied screenshots locally; never sends pixels to a remote API."""
import json
from pathlib import Path
from PIL import Image
from itemsniper.vision import Vision

root = Path.home() / 'Pictures' / 'Screenshots'
timestamps = ['223416', '223437', '223447', '223839', '224033', '224657', '224755']
output = Path('data/frame-validation')
output.mkdir(parents=True, exist_ok=True)
vision = Vision()
catalog = json.loads(Path('data/catalog.json').read_text(encoding='utf-8'))
for stamp in timestamps:
    path = next(root.glob(f'*2026-11-11 {stamp}.png'))
    image = Image.open(path).convert('RGB')
    region = image.crop((1226, 48, 1919, 949))
    lines = vision.text(region)
    result = {'file': str(path), 'text': [{'text': text, 'score': score, 'box': box.tolist()} for text, score, box in lines]}
    (output / (stamp + '-ocr.json')).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(stamp, [text for text, _, _ in lines], flush=True)
