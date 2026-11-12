import copy
import tempfile
import unittest
from pathlib import Path

from itemsniper.overlay import annotation
from itemsniper.service import Service


class RaidTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.service=Service(Path(self.temp.name))
        self.service.set_catalog({'items':[{'id':'b','name':'Bolts','name_ru':'Болты'}],
            'stations':[{'name':'Workbench','levels':[{'level':1,'items':[{'name':'Bolts','count':2}]}]}]})
        self.service.edit_levels({'Workbench':0})
        self.service.publish()

    def hit(self,count=1,fir='yes',x=0):
        return {'name':'Bolts','count':count,'fir':fir,'box':(x,0,64,64),'score':.99,'method':'slot-image'}

    def observe(self,hits,analysis=None):
        for _ in range(2):
            self.service.stage_scan({'inventory':hits},.1,analysis={'inventory':analysis or {'panel_visible':True,'waiting':[]}})

    def test_held_in_raid_suppresses_search_without_stash_transfer(self):
        self.observe([self.hit(2)])
        self.assertEqual(self.service.needed()['Bolts']['remaining'],0)
        found=self.service.classify([self.hit()])[0]
        self.assertEqual(found['status'],'surplus')
        self.assertEqual(found['take_count'],0)
        self.assertEqual(self.service.state.value['inventory'],{})

    def test_repeated_frames_never_add_again_and_drop_releases_budget(self):
        for _ in range(8):
            self.observe([self.hit()])
        self.assertEqual(self.service.raid.items['Bolts']['count'],1)
        self.observe([])
        self.assertEqual(self.service.needed()['Bolts']['remaining'],2)

    def test_closed_inventory_does_not_zero_observations(self):
        self.observe([self.hit(2)])
        self.observe([],{'panel_visible':False})
        self.assertEqual(self.service.needed()['Bolts']['remaining'],0)

    def test_character_snapshot_replaced_but_stash_added_once(self):
        self.service.edit_inventory('Персонаж',{'Bolts':{'count':1,'fir':1}},'character')
        self.service.edit_inventory('Ящик',{'Bolts':{'count':1,'fir':1}},'stash')
        self.observe([self.hit()])
        self.assertEqual(self.service.needed()['Bolts']['owned'],2)

    def test_protection_switch_ignores_raid_possessions(self):
        self.observe([self.hit(2)])
        self.service.settings({'protect_surplus':False})
        self.assertEqual(self.service.needed()['Bolts']['remaining'],2)
        self.assertTrue(self.service.classify([self.hit()])[0]['eligible'])

    def test_loot_is_not_possession_and_stack_has_take_limit(self):
        self.service.stage_scan({'loot':[self.hit(10)]},.1)
        self.assertIsNone(self.service.raid.items)
        result=self.service.classify([self.hit(10),self.hit(x=70)])
        self.assertEqual(result[0]['take_count'],2)
        self.assertEqual(result[1]['status'],'surplus')

    def test_hidden_slot_waits_then_reveals_without_changing_published_list(self):
        published=copy.deepcopy(self.service.state.value['published'])
        self.service.stage_scan({'loot':[]},.1,analysis={'loot':{'panel_visible':True,'waiting':[(0,0,64,64)]}})
        self.assertEqual(len(self.service.reveals.regions['loot']),1)
        self.service.stage_scan({'loot':[self.hit()]},.1,analysis={'loot':{'panel_visible':True,'waiting':[]}})
        self.assertEqual(self.service.reveals.revealed['loot'],1)
        self.assertEqual(self.service.reveals.regions['loot'],[])
        self.assertEqual(self.service.state.value['published'],published)

    def test_unknown_fir_does_not_fill_fir_budget(self):
        self.service.edit_target('Bolts',1,True)
        self.service.publish()
        self.observe([self.hit(3,'unknown')])
        self.assertEqual(self.service.needed()['Bolts']['remaining'],1)
        self.assertEqual(self.service.classify([self.hit(fir='unknown')])[0]['status'],'uncertain')

    def test_overlay_controls_and_absolute_coordinates(self):
        settings=self.service.state.value
        settings.update(overlay_labels=False,overlay_outlines=True)
        hit={**self.hit(),'status':'surplus','take_count':0}
        value=annotation(hit,{'left':-100,'top':30},{'short_name_ru':'Болты'},settings)
        self.assertEqual(value['box'],(-100,30,64,64))
        self.assertFalse(value['label_visible'])
        self.assertTrue(value['outline_visible'])
        self.assertEqual(value['color'],settings['color_surplus'])


if __name__=='__main__':
    unittest.main()
