import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from itemsniper.vision import Vision


class VisionTests(unittest.TestCase):
    def test_icon_multiscale_dedup_and_multiple_instances(self):
        with tempfile.TemporaryDirectory() as temp:
            template = np.random.default_rng(42).integers(0, 255, (40, 40, 3), dtype=np.uint8)
            path = Path(temp) / 'icon.png'
            Image.fromarray(template).save(path)
            frame = np.zeros((200, 300, 3), dtype=np.uint8)
            frame[30:70, 30:70] = template
            frame[110:150, 180:220] = template
            vision = Vision()
            vision.text = lambda image: []
            hits = vision.items(Image.fromarray(frame), {'icons': {'Bolts': str(path)}})
            self.assertEqual(len(hits), 2)
            self.assertTrue(all(h['name'] == 'Bolts' for h in hits))

    def test_hideout_candidate_from_nearby_level(self):
        vision = Vision()
        vision.text = lambda image: [
            ('Workbench', .99, np.array([[0, 0], [100, 0], [100, 20], [0, 20]])),
            ('Level 2', .99, np.array([[0, 40], [100, 40], [100, 60], [0, 60]]))]
        candidates, _ = vision.hideout(None, {'stations': [{'name': 'Workbench', 'levels': [{'level': 1}, {'level': 2}]}]})
        self.assertEqual(candidates, {'Workbench': 2})

    def test_russian_and_english_slot_labels_without_tooltips(self):
        catalog = {'items': [{'id': 'bolts', 'name': 'Bolts', 'name_ru': 'Болты', 'short_name': 'Bolts', 'short_name_ru': 'Болты'}]}
        vision = Vision()
        for label in ('Болты', 'Bolts'):
            vision.text = lambda image, text=label: [(text, .99, np.array([[3, 3], [45, 3], [45, 14], [3, 14]]))]
            hits = vision.items(Image.new('RGB', (128, 128)), catalog)
            self.assertEqual(len(hits), 1)
            self.assertEqual(hits[0]['method'], 'slot-label')
        vision.text = lambda image: [('Bolts', .99, np.array([[20, 35], [110, 35], [110, 65], [20, 65]]))]
        self.assertEqual(vision.items(Image.new('RGB', (128, 128)), catalog), [])

    def test_calibrated_fir_present_absent_and_unknown(self):
        template = Image.new('RGB', (13, 12), 'black')
        ImageDraw.Draw(template).line([(1, 5), (5, 10), (11, 1)], fill='white', width=2)
        frame = Image.new('RGB', (64, 64), 'black')
        frame.paste(template, (48, 49))
        self.assertEqual(Vision.checkmark(frame, (0, 0, 64, 64), np.asarray(template))[0], 'yes')
        self.assertEqual(Vision.checkmark(Image.new('RGB', (64, 64)), (0, 0, 64, 64), np.asarray(template))[0], 'no')
        self.assertEqual(Vision.checkmark(Image.new('RGB', (64, 64), 'white'), (0, 0, 64, 64), np.asarray(template))[0], 'unknown')

    def test_slot_quantity_ocr(self):
        vision = Vision()
        vision.text = lambda image: [
            ('Болты', .99, np.array([[3, 3], [45, 3], [45, 14], [3, 14]])),
            ('12', .98, np.array([[48, 49], [60, 49], [60, 61], [48, 61]]))]
        hits = vision.items(Image.new('RGB', (64, 64)), {'items': [{'id': 'bolts', 'name': 'Bolts', 'name_ru': 'Болты'}]})
        self.assertEqual(hits[0]['count'], 12)


if __name__ == '__main__':
    unittest.main()
