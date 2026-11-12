"""Manual integration check: downloads official OCR models on first run."""
from PIL import Image, ImageDraw, ImageFont
from itemsniper.vision import Vision

image = Image.new('RGB', (1000, 220), 'white')
draw = ImageDraw.Draw(image)
font = ImageFont.truetype('arial.ttf', 36)
draw.text((20, 25), 'Болты Уровень 2', fill='black', font=font)
draw.text((20, 110), 'Bolts Workbench Level 2', fill='black', font=font)
lines = [text for text, _, _ in Vision().text(image)]
print(lines)
assert any('Болты' in text for text in lines), lines
assert any('Bolts' in text for text in lines), lines
print('RU / EN OCR integration: OK')
