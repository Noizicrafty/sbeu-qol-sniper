import unittest
from unittest.mock import Mock

import numpy as np
from PIL import Image

from itemsniper.vision import Vision


class FrameCacheTests(unittest.TestCase):
    def test_unchanged_frame_reuses_and_revealed_cell_is_read_again(self):
        vision=Vision()
        catalog={}
        image=np.zeros((800,800,3),dtype=np.uint8)
        def infer(frame,*args):
            visible=bool(np.asarray(frame).max())
            vision.last_analysis={'panel_visible':True,'waiting':[] if visible else [(300,300,64,64)]}
            return [{'name':'new item','box':(64,64,64,64)}] if visible else []
        vision.items=Mock(side_effect=infer)
        self.assertEqual(vision.scan(Image.fromarray(image),catalog),[])
        vision.scan(Image.fromarray(image),catalog)
        self.assertEqual(vision.items.call_count,1)
        self.assertTrue(vision.last_analysis['frame_reused'])
        image[300:364,300:364]=255
        hits=vision.scan(Image.fromarray(image),catalog)
        self.assertEqual(vision.items.call_count,2)
        self.assertEqual(hits[0]['box'],(300,300,64,64))
        self.assertEqual(vision.last_analysis['waiting'],[])
        self.assertTrue(vision.last_analysis['incremental'])

    def test_views_have_independent_caches(self):
        vision=Vision();catalog={}
        def infer(*args):
            vision.last_analysis={'waiting':[]}
            return []
        vision.items=Mock(side_effect=infer)
        frame=Image.new('RGB',(100,100))
        vision.scan(frame,catalog,view_key='loot')
        vision.scan(frame,catalog,view_key='inventory')
        self.assertEqual(vision.items.call_count,2)
