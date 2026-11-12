import copy
import tempfile
import time
import unittest
from pathlib import Path

from itemsniper.service import Service


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.service = Service(Path(self.temp.name))
        self.service.set_catalog({'items': [{'id': 'bolts', 'name': 'Bolts', 'name_ru': 'Болты', 'short_name': 'Bolts', 'short_name_ru': 'Болты'}],
                                  'stations': [{'name': 'Workbench', 'name_ru': 'Верстак', 'levels': [
                                      {'level': 1, 'items': [{'name': 'Bolts', 'count': 2, 'fir': True}]}]}]})
        self.hit = {'name': 'Bolts', 'score': .99, 'fir': 'yes', 'count': 1, 'box': (0, 0, 64, 64), 'method': 'slot-image'}

    def test_live_frames_never_change_published_or_inventory(self):
        self.service.edit_target('Bolts', 2, True)
        before = copy.deepcopy(self.service.state.value)
        self.service.stage_scan({'loot': [self.hit], 'inventory': [self.hit]}, .01)
        self.assertEqual(before, self.service.state.value)
        self.service.publish()
        self.assertEqual(len(self.service.state.value['published']), 1)
        self.service.stage_scan({'loot': []}, .01)
        self.assertEqual(len(self.service.state.value['published']), 1)

    def test_draft_edits_do_not_change_active_targets_until_bind(self):
        self.service.edit_target('Bolts', 2, True)
        self.service.publish()
        self.service.edit_target('Bolts', 5, False)
        self.assertEqual(self.service.state.value['active_targets']['Bolts']['required'], 2)
        self.service.publish()
        self.assertEqual(self.service.state.value['active_targets']['Bolts']['required'], 5)

    def test_unknown_fir_not_eligible_for_fir_only_upgrade(self):
        self.service.edit_levels({'Workbench': 0})
        self.hit['fir'] = 'unknown'
        self.service.stage_scan({'loot': [self.hit]}, .01)
        self.assertFalse(self.service.publish()[0]['eligible'])
        self.hit['fir'] = 'yes'
        self.service.stage_scan({'loot': [self.hit]}, .01)
        self.assertTrue(self.service.publish()[0]['eligible'])

    def test_stale_frames_cannot_publish_found_items(self):
        self.service.edit_target('Bolts', 2, False)
        self.service.stage_scan({'loot': [self.hit]}, .01, captured_at=time.time()-30)
        self.assertEqual(self.service.publish(), [])

    def test_inventory_f9_stages_only_then_replace(self):
        self.service.stage_scan({'inventory': [self.hit]}, .01)
        self.service.stage_inventory()
        self.assertEqual(self.service.state.value['inventory'], {})
        self.service.edit_inventory('Персонаж', {'Bolts': {'count': 2, 'fir': 1}})
        self.service.edit_inventory('Персонаж', {'Bolts': {'count': 1, 'fir': 0}})
        self.assertEqual(self.service.state.owned()['Bolts'], 1)

    def test_bilingual_search_and_validation(self):
        self.assertEqual(self.service.search('болты')['items'][0]['name'], 'Bolts')
        self.assertEqual(self.service.search('bolts')['items'][0]['name_ru'], 'Болты')
        with self.assertRaises(ValueError):
            self.service.edit_inventory('Персонаж', {'Bolts': {'count': 1, 'fir': 2}})
        with self.assertRaises(ValueError):
            self.service.edit_target('Unknown', 2, False)
        with self.assertRaises(ValueError):
            self.service.settings({'interval': float('nan')})

    def test_seasonal_fir_rule_does_not_disable_manual_fir(self):
        self.service.edit_levels({'Workbench': 0})
        self.service.edit_target('Bolts', 1, True)
        self.service.settings({'hideout_fir_required': False})
        need = self.service.state.needed(self.service.catalog)['Bolts']
        self.assertEqual(need['required'], 3)
        self.assertEqual(need['fir_required'], 1)

    def test_dictionary_preserves_ids_with_same_display_name(self):
        self.service.set_catalog({'items': [
            {'id': 'a', 'name': 'Example', 'name_ru': 'Пример'},
            {'id': 'b', 'name': 'Example', 'name_ru': 'Пример'}]})
        results = self.service.search('Example')['items']
        self.assertEqual(len(results), 2)
        self.assertEqual({r['id'] for r in results}, {'a', 'b'})


if __name__ == '__main__':
    unittest.main()
