import json
import unittest
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from itemsniper.slots import SlotGeometry
from itemsniper.vision import Vision

FIXTURES = Path(__file__).with_name('fixtures')


class SlotGeometryTests(unittest.TestCase):
    def test_actual_shifted_bag_grid_and_three_cell_object(self):
        image = Image.open(FIXTURES / 'offset-loot.png').convert('RGB')
        rows = json.loads((FIXTURES / 'offset-loot-ocr.json').read_text(encoding='utf-8'))
        geometry = SlotGeometry(image)
        shus = next(row for row in rows if row['text'] == 'Shus')
        slickers = next(row for row in rows if row['text'] == 'Slickers')
        x, y, w, h = geometry.label_box(np.array(shus['box']))
        self.assertLess(abs(x-13), 3)
        self.assertLess(abs(y-8), 3)
        self.assertTrue(60 <= w <= 68)
        self.assertTrue(185 <= h <= 196)
        self.assertEqual(geometry.label_box(np.array(slickers['box']))[2:], (63, 63))

    def test_same_item_can_appear_twice_at_unaligned_origins(self):
        image = Image.new('RGB', (240, 170), '#101010')
        draw = ImageDraw.Draw(image)
        captions = []
        for x, y in ((17, 9), (149, 91)):
            draw.rectangle((x, y, x+64, y+64), outline='#999999', width=1)
            captions.append(('Болты', .99, np.array([[x+20,y+3],[x+61,y+3],[x+61,y+14],[x+20,y+14]])))
        vision = Vision()
        vision.text = lambda image: captions
        hits = vision.items(image, {'items': [{'id': 'bolts', 'name': 'Bolts', 'name_ru': 'Болты'}]})
        self.assertEqual(len(hits), 2)
        self.assertNotEqual(hits[0]['box'], hits[1]['box'])

    def test_hatched_unsearched_area_does_not_create_items(self):
        image = Image.new('RGB', (300, 180), '#151515')
        draw = ImageDraw.Draw(image)
        for x in range(-180, 300, 12):
            draw.line((x, 0, x+180, 180), fill='#303030', width=5)
        vision = Vision()
        vision.text = lambda image: [('НЕ ОБЫСКАНО', .99, np.array([[50,70],[250,70],[250,100],[50,100]]))]
        self.assertEqual(vision.items(image, {'items': [{'id': 'bolts', 'name': 'Bolts', 'name_ru': 'Болты'}]}), [])
        self.assertTrue(vision.last_analysis['unsearched'])


if __name__ == '__main__':
    unittest.main()
