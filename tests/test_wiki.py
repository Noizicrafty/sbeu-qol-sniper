import unittest
from itemsniper.wiki import parse_html


class WikiTests(unittest.TestCase):
    def test_requirements_not_bonuses_or_prerequisites(self):
        html = '''<h2>Workbench</h2><table><tbody>
        <tr><th>Level</th><th>Requirements</th><th>Function</th></tr>
        <tr><td>1</td><td><ul>
        <li>2 <a href="/wiki/Bolts" title="Bolts">Bolts</a> found in raid
        <img src="https://static.wikia.nocookie.net/test.png"></li>
        <li>Level 2 <a title="Vents" href="/wiki/Vents">Vents</a></li>
        </ul></td><td>Craft items</td></tr></tbody></table>'''
        result = parse_html(html)
        self.assertEqual(result['stations'][0]['levels'][0]['items'], [
            {'name': 'Bolts', 'count': 2, 'fir': True,
             'wiki': 'https://escapefromtarkov.fandom.com/wiki/Bolts'}])
        self.assertIn('Bolts', result['images'])

    def test_block_page_rejected(self):
        with self.assertRaises(ValueError):
            parse_html('<html>Access denied</html>')

    def test_real_wiki_caption_row_and_numeric_item_name(self):
        html = '''<h2>Modules</h2><table><tbody>
        <tr><th colspan="4">Bitcoin Farm<br>Note: requires power</th></tr>
        <tr><th>Level</th><th>Requirements</th><th>Function</th></tr>
        <tr><th>3</th><td><ul><li>2 <a title="6-STEN-140-M military battery"
        href="/wiki/6-STEN-140-M_military_battery">6-STEN-140-M military battery</a></li>
        <li>25 <a title="CPU fan" href="/wiki/CPU_fan">CPU fan</a> found <a title="Found in raid">in raid</a></li>
        </ul></td><td>Farm</td></tr></tbody></table>'''
        station = parse_html(html)['stations'][0]
        self.assertEqual(station['name'], 'Bitcoin Farm')
        self.assertEqual(station['levels'][0]['items'][0]['count'], 2)
        self.assertTrue(station['levels'][0]['items'][1]['fir'])


if __name__ == '__main__':
    unittest.main()
