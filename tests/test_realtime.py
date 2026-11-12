import threading
import unittest
from unittest.mock import Mock

import numpy as np
from PIL import Image

from itemsniper.realtime import RealtimeVision


class RealtimeTests(unittest.TestCase):
    def runtime(self):
        runtime=RealtimeVision.__new__(RealtimeVision)
        runtime.fast=Mock();runtime.fast.scan.return_value=[];runtime.fast.last_analysis={}
        runtime.lock=threading.RLock();runtime.pending={};runtime.submitted={}
        runtime.refined={};runtime.full_refined={};runtime.wake=threading.Event()
        return runtime

    def test_background_refinement_never_blocks_or_requires_publish(self):
        runtime=self.runtime();catalog={};frame=Image.new('RGB',(80,80),'white')
        hits=runtime.scan(frame,catalog)
        self.assertEqual(hits,[])
        self.assertIn('loot',runtime.pending)
        self.assertTrue(runtime.wake.is_set())
        runtime.fast.scan.assert_called_once()

    def test_whole_panel_search_yields_to_newly_revealed_slots(self):
        runtime=self.runtime();runtime.urgent=lambda:True
        self.assertEqual(runtime.scan(Image.new('RGB',(80,80)),{}),[])
        runtime.fast.scan.assert_not_called()
        self.assertTrue(runtime.last_analysis['deferred_for_new_items'])

    def test_stale_background_item_is_rejected_after_scene_change(self):
        runtime=self.runtime();catalog={};frame=Image.new('RGB',(80,80),'white')
        hit={'name':'old item','box':(10,10,32,32),'count':1}
        runtime.refined['loot']=(np.zeros((80,80,3),dtype=np.uint8),[hit],id(catalog),.88,64)
        self.assertEqual(runtime.scan(frame,catalog),[])

    def test_matching_background_result_appears_without_bind(self):
        runtime=self.runtime();catalog={};frame=Image.new('RGB',(80,80),'white')
        hit={'name':'new item','box':(10,10,32,32),'count':1}
        runtime.refined['loot']=(np.asarray(frame),[hit],id(catalog),.88,64)
        self.assertEqual(runtime.scan(frame,catalog),[hit])

    def test_changed_threshold_invalidates_background_result(self):
        runtime=self.runtime();catalog={};frame=Image.new('RGB',(80,80),'white')
        runtime.refined['loot']=(np.asarray(frame),[{'name':'old','box':(0,0,32,32)}],id(catalog),.88,64)
        self.assertEqual(runtime.scan(frame,catalog,threshold=.95),[])
