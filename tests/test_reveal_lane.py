import threading
import time
import unittest
import tempfile
from pathlib import Path
from unittest.mock import Mock,patch
from PIL import Image
import cv2
import numpy as np
from itemsniper.reveal import RevealDetector,inventory_visible
from itemsniper.vision import Vision


class RevealTests(unittest.TestCase):
    def detector(self):return RevealDetector(None)
    def test_changed_slot_is_located_without_full_frame_recognition(self):
        detector=self.detector();before=Image.new('RGB',(1920,1080),(30,30,30))
        detector.regions(before);after=before.copy();after.paste((220,220,220),(1300,100,1364,164))
        boxes=detector.regions(after)
        self.assertTrue(any(x<=1300 and y<=100 and X>=1364 and Y>=164 for x,y,X,Y in boxes))
        self.assertTrue(all((X-x)*(Y-y)<300*300 for x,y,X,Y in boxes))
        self.assertEqual(detector.regions(after),[])
    def test_latest_reveal_precedes_initial_sweep(self):
        detector=self.detector();detector.enqueue([(0,50,240,290),(300,50,540,290)],1)
        detector.enqueue([(1200,100,1350,250)],2)
        self.assertEqual(detector.queue.popleft(),((1200,100,1350,250),2))
    def test_repeated_region_does_not_grow_work_queue(self):
        detector=self.detector()
        for i in range(100):detector.enqueue([(1200,100,1350,250)],i)
        self.assertEqual(len(detector.queue),1)
        self.assertEqual(detector.queue[0][1],99)
    def test_art_detection_is_emitted_before_caption_recognition_finishes(self):
        detector=self.detector();entered=threading.Event();release=threading.Event();emitted=threading.Event()
        hit={'name':'new','box':(10,10,64,64),'count':1}
        detector.art=Mock();detector.art.items.return_value=[hit]
        detector.ocr=Mock()
        def slow(*args,**kwargs):entered.set();release.wait(2);return [hit]
        detector.ocr.items.side_effect=slow
        results=[]
        def emit(hits,method):results.extend(hits);emitted.set()
        worker=threading.Thread(target=lambda:detector.recognize(Image.new('RGB',(200,200)),(20,30,180,190),{},64,emit))
        worker.start()
        try:
            self.assertTrue(entered.wait(1));self.assertTrue(emitted.is_set())
            self.assertEqual(results[0]['box'],(30,40,64,64))
        finally:release.set();worker.join(2)
    def test_caption_pass_reuses_image_hits_and_geometry(self):
        detector=self.detector();detector.art=Mock();detector.art.items.return_value=[]
        detector.ocr=Mock();detector.ocr.items.return_value=[]
        detector.recognize(Image.new('RGB',(200,200)),(0,0,200,200),{},64,lambda *args:None)
        art=detector.art.items.call_args.kwargs;ocr=detector.ocr.items.call_args.kwargs
        self.assertIs(art['geometry'],ocr['geometry']);self.assertEqual(ocr['seed_hits'],[])
    def test_selected_items_gate_rejects_quests(self):
        image=Image.new('RGB',(1920,1080));self.assertFalse(inventory_visible(image))
        image.paste((230,230,230),(184,15,330,35));self.assertTrue(inventory_visible(image))
    def test_opposite_rotation_is_verified_on_first_visual_pass(self):
        gray=np.random.default_rng(8).integers(0,255,(64,128),dtype=np.uint8)
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'icon.png';Image.fromarray(gray).save(path)
            rotated=np.rot90(gray,3);frame=np.zeros((144,80),dtype=np.uint8);frame[8:136,8:72]=rotated
            hits=Vision().slot_images(frame,{'item':{'path':str(path),'rotation':1}},[(8,8,64,128)],.98,64)
            self.assertTrue(any(h['rotation']==270 for h in hits))


if __name__=='__main__':unittest.main()
