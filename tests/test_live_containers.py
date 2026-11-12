import unittest
import tempfile
from pathlib import Path
import numpy as np
from PIL import Image
from itemsniper.live import FrameTracker
from itemsniper.containers import detect_containers,visible_contents,ContainerRegistry
from itemsniper.stash import StashSession
from itemsniper.vision import caption_key


class LiveTests(unittest.TestCase):
    def setUp(self):
        self.image=Image.fromarray(np.random.default_rng(4).integers(0,255,(180,240,3),dtype=np.uint8))
        self.hit={'name':'test','box':(30,40,64,64),'count':1,'fir':'yes'}
    def test_removed_item_invalidates_frame_without_model(self):
        tracker=FrameTracker();tracker.install(self.image,self.image,[self.hit])
        self.assertEqual(len(tracker.update(self.image)),1)
        blank=self.image.copy();blank.paste((0,0,0),(30,40,94,104))
        self.assertEqual(tracker.update(blank),[])
    def test_stale_inference_cannot_restore_removed_item(self):
        tracker=FrameTracker();blank=Image.new('RGB',self.image.size)
        tracker.install(self.image,blank,[self.hit]);self.assertEqual(tracker.update(blank),[])
    def test_resolution_change_drops_old_boxes(self):
        tracker=FrameTracker();tracker.install(self.image,self.image,[self.hit])
        self.assertEqual(tracker.update(self.image.resize((480,360))),[])
    def test_magazine_caption_confusions(self):
        self.assertEqual(caption_key('C6:3x5'),caption_key('Сб.3x5'))
        self.assertNotEqual(caption_key('C6:3x5'),caption_key('Сб.3x4'))
    def test_separate_cases_and_repeated_frames(self):
        session=StashSession();session.start()
        for _ in range(3):
            for key in ['container:1','container:2']:session.observe_view(key,self.image,[self.hit])
        self.assertEqual(session.items()['test']['count'],2)
        self.assertEqual(session.snapshot()['views'],2)
    def test_registry_one_to_one_even_identical_contents(self):
        registry=ContainerRegistry();panel={'bounds':(0,0,240,180),'cell':64}
        views=[(panel,self.image,[]),(panel,self.image,[])]
        keys=[v[0] for v in registry.identify(views)]
        self.assertEqual(len(set(keys)),2)
        self.assertEqual(keys,[v[0] for v in registry.identify(views)])
    def test_stash_resize_is_not_merged(self):
        session=StashSession();session.start();self.assertTrue(session.begin_frame((1920,1080)))
        self.assertFalse(session.begin_frame((1280,720)))
    def test_plain_screen_not_a_container(self):
        self.assertEqual(detect_containers(Image.new('RGB',(1920,1080))),[])


if __name__=='__main__':unittest.main()
