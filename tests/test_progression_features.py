import tempfile
import unittest
from pathlib import Path
import numpy as np
from PIL import Image
from itemsniper.progression import resolve_hideout,QuestProgress
from itemsniper.service import Service
from itemsniper.automatic import AutoCalibration
from itemsniper.stash import StashCollector
from itemsniper.overlay import annotation
from itemsniper.questscan import checkbox


class ProgressionTests(unittest.TestCase):
    def test_hideout_builds_transitive_prerequisites_and_demolishes_dependents(self):
        stations=[{'name':n,'levels':[{'level':1},{'level':2}]} for n in ['A','B','C']]
        rules=[{'name':'B','levels':[{'level':2,'requirements':[{'name':'A','level':1}]}]},
               {'name':'C','levels':[{'level':1,'requirements':[{'name':'B','level':2}]}]}]
        built=resolve_hideout({}, {'C':1},stations,rules)
        self.assertEqual(built,{'A':1,'B':2,'C':1})
        self.assertEqual(resolve_hideout(built,{'A':0},stations,rules),{'A':0,'B':0,'C':0})

    def tasks(self):
        return [{'id':i,'name_ru':i,'kind':'side','objectives':[{'id':i+'o','count':2,'type':'giveItem','items':['item']}],
            'taskRequirements':req} for i,req in [('a',[]),('b',[{'task':'a','status':['complete']}]),('c',[{'task':'b','status':['complete']}]),('alternative',[{'task':'a','status':['failed','complete']}])]]

    def test_demolition_does_not_reset_unrelated_legacy_levels(self):
        stations=[{'name':n,'levels':[{'level':1},{'level':2}]} for n in ['A','B','Other','Unknown']]
        rules=[{'name':'B','levels':[{'level':1,'requirements':[{'name':'A','level':1}]}]},
               {'name':'Other','levels':[{'level':1,'requirements':[{'name':'Unknown','level':1}]}]}]
        result=resolve_hideout({'A':2,'B':1,'Other':2},{'A':0},stations,rules)
        self.assertEqual(result['B'],0);self.assertEqual(result['Other'],2)

    def test_active_later_quest_completes_mandatory_chain(self):
        state={};q=QuestProgress(self.tasks(),state);q.update('c','active')
        self.assertEqual(q.value('a')['status'],'complete');self.assertTrue(q.value('a')['objectives']['ao']['done'])
        self.assertEqual(q.value('b')['status'],'complete');self.assertTrue(q.value('b')['inferred'])

    def test_alternative_failed_gate_is_not_forced_complete(self):
        q=QuestProgress(self.tasks(),{});q.update('alternative','active');self.assertEqual(q.value('a')['status'],'locked')

    def test_completed_objective_disappears_from_yellow_targets(self):
        q=QuestProgress(self.tasks(),{});q.update('a','active');records={'Item':{'id':'item'}}
        self.assertIn('Item',q.targets(records));q.update('a',objectives={'ao':{'done':True,'count':2}})
        self.assertNotIn('Item',q.targets(records))

    def test_story_mandatory_points_are_tracked_automatically(self):
        tasks=self.tasks();tasks[0]['kind']='story';tasks[0]['objectives'].append({'id':'optional','type':'giveItem','items':['optional'],'count':1,'optional':True})
        q=QuestProgress(tasks,{});q.update('a','active')
        targets=q.targets({'Item':{'id':'item'},'Optional':{'id':'optional'}})
        self.assertIn('Item',targets);self.assertNotIn('Optional',targets)

    def test_invalid_progress_does_not_overwrite_existing_state(self):
        q=QuestProgress(self.tasks(),{});q.update('a','active')
        with self.assertRaises(ValueError):q.update('a',objectives={'ao':{'done':False,'count':-1}})
        self.assertEqual(q.value('a')['objectives'],{})

    def test_nullable_api_count_uses_checkbox_goal(self):
        tasks=self.tasks();tasks[0]['objectives'][0]['count']=None
        q=QuestProgress(tasks,{});q.update('a','active')
        self.assertEqual(q.targets({'Item':{'id':'item'}})['Item'][0]['remaining'],1)
        q.update('a','complete');self.assertEqual(q.value('a')['objectives']['ao']['count'],1)

class CatalogTests(unittest.TestCase):
    def test_pagination_filters_and_last_page(self):
        with tempfile.TemporaryDirectory() as d:
            service=Service(Path(d));service.set_catalog({'items':[{'id':str(i),'name':f'Item {i:03}','name_ru':f'Предмет {i:03}','types':['food' if i%2 else 'tool'],'categories':[{'id':'cat','name':'Категория'}]} for i in range(103)]})
            found=[]
            for page in range(1,10):
                value=service.search(limit=12,page=page);found.extend(v['id'] for v in value['items'])
            self.assertEqual(len(found),103);self.assertEqual(len(set(found)),103)
            filtered=service.search(kind='food');self.assertEqual(filtered['total'],51)
            self.assertEqual(service.search(category='other')['total'],0)

class StashTests(unittest.TestCase):
    def hit(self,y=200):return {'name':'Item','box':(40,y,64,64),'fir':'yes','count':1}
    def test_same_frame_never_adds_copies(self):
        s=StashCollector();s.start();image=Image.new('RGB',(400,500))
        for _ in range(8):s.observe(image,[self.hit()])
        self.assertEqual(s.items()['Item']['count'],1)
        self.assertEqual(s.finish()['scope'],'stash')

    def test_scrolling_overlap_is_deduplicated(self):
        rng=np.random.default_rng(15);canvas=rng.integers(0,255,(800,400,3),dtype=np.uint8)
        s=StashCollector();s.start();s.observe(Image.fromarray(canvas[:500]),[self.hit()])
        s.observe(Image.fromarray(canvas[100:600]),[self.hit(100),self.hit(400)])
        self.assertFalse(s.warning);self.assertAlmostEqual(s.offset,100,delta=3)
        self.assertEqual(s.items()['Item']['count'],2)

    def test_unalignable_page_is_not_added(self):
        s=StashCollector();s.start();s.observe(Image.new('RGB',(400,500),'black'),[self.hit()])
        s.observe(Image.new('RGB',(400,500),'white'),[self.hit(300)])
        self.assertTrue(s.warning);self.assertEqual(s.items()['Item']['count'],1)

    def test_ambiguous_objects_are_not_silently_owned(self):
        s=StashCollector();s.start();s.observe(Image.new('RGB',(400,500)),[{**self.hit(),'ambiguous':True}])
        self.assertEqual(s.items(),{})

class CalibrationTests(unittest.TestCase):
    def test_resolution_cache_survives_restart_and_can_be_cleared(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'autocalibration.json';cal=AutoCalibration(path)
            value=cal.resolve(Image.new('RGB',(1280,720)),{'width':1280,'height':720,'dpi':96})
            self.assertAlmostEqual(value['cell'],64*720/1080,places=1)
            self.assertEqual(AutoCalibration(path).entries,cal.entries)
            cal.clear();self.assertFalse(path.exists())

    def test_quest_annotation_uses_yellow_center_circle(self):
        value=annotation({'box':(10,20,64,64),'name':'Item','quest_needed':True},{'left':100,'top':50},{},{'overlay_labels':True,'overlay_outlines':True})
        self.assertTrue(value['quest']);self.assertEqual(value['color'],'#ffda45')

    def test_checkbox_empty_and_checked_are_distinguished(self):
        from PIL import ImageDraw
        image=Image.new('RGB',(300,100),'#101010');draw=ImageDraw.Draw(image)
        draw.rectangle((30,35,49,54),outline='#eeeecc',width=2)
        box=np.array([[65,34],[200,34],[200,56],[65,56]])
        self.assertFalse(checkbox(image,box))
        draw.line((34,44,39,49,46,39),fill='white',width=3)
        self.assertTrue(checkbox(image,box))
