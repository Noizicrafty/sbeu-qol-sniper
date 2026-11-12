import tempfile
import unittest
from pathlib import Path

from itemsniper.core import State


class PlannerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.state = State(Path(self.temp.name) / 'state.json')
        self.catalog = {'stations': [
            {'name': 'Workbench', 'levels': [
                {'level': 1, 'items': [{'name': 'Bolts', 'count': 2}]},
                {'level': 2, 'items': [{'name': 'Bolts', 'count': 3, 'fir': True}]}]},
            {'name': 'Water', 'levels': [{'level': 1, 'items': [{'name': 'Bolts', 'count': 4}]}]}
        ]}

    def test_unknown_stations_excluded(self):
        self.assertEqual(self.state.needed(self.catalog), {})

    def test_next_and_all_levels_aggregate(self):
        self.state.value['levels'] = {'Workbench': 0, 'Water': 0}
        self.assertEqual(self.state.needed(self.catalog)['Bolts']['required'], 6)
        self.assertEqual(self.state.needed(self.catalog, True)['Bolts']['required'], 9)

    def test_snapshot_replacement_and_persistence(self):
        self.state.value['levels'] = {'Workbench': 0}
        self.state.value['inventory']['Character'] = {'Bolts': {'count': 1, 'fir': 0}}
        self.state.value['inventory']['Character'] = {'Bolts': {'count': 2, 'fir': 0}}
        self.state.save()
        restored = State(self.state.path)
        self.assertEqual(restored.needed(self.catalog)['Bolts']['remaining'], 0)

    def test_fir_cannot_be_satisfied_by_regular_items(self):
        self.state.value['levels'] = {'Workbench': 1}
        self.state.value['inventory']['Character'] = {'Bolts': {'count': 10, 'fir': 1}}
        self.assertEqual(self.state.needed(self.catalog)['Bolts']['remaining'], 2)


if __name__ == '__main__':
    unittest.main()
