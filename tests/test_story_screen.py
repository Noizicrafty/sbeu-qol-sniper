import json
import unittest
from pathlib import Path
import numpy as np
from PIL import Image,ImageDraw
from itemsniper.questscan import parse_quests


class StoryScreenTests(unittest.TestCase):
    def test_all_six_visible_points_and_counter_from_recorded_ocr(self):
        fixture=json.loads((Path(__file__).parent/'fixtures/story-visible-lines.json').read_text(encoding='utf8'))
        image=Image.new('RGB',(1920,1080),'#101010');draw=ImageDraw.Draw(image)
        for y in [399,433,525,557,588,619]:draw.rectangle((194,y,212,y+18),outline='#ddddbb',width=2)
        lines=[(l['text'],l['score'],np.asarray(l['box'])) for l in fixture['lines']]
        result=parse_quests(image,lines,[fixture['task']])
        self.assertEqual(result['story'],'story:falling-skies')
        self.assertEqual(len(result['objectives']),6)
        counter=result['objectives']['68b5758c09b1506a5cd4e3a3']
        self.assertEqual((counter['count'],counter['target']),(113,2000))
        self.assertTrue(counter['visible_optional'])
        self.assertTrue(all(not p['done'] for p in result['objectives'].values()))
        draw.line((198,442,202,447,209,437),fill='white',width=3)
        result=parse_quests(image,lines,[fixture['task']])
        self.assertTrue(result['objectives']['678f6ec00199b227bbf61473']['done'])
