import tempfile
import unittest
from pathlib import Path

import requests

from itemsniper.service import Service
from itemsniper.webserver import LocalWeb


class WebTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.service = Service(Path(self.temp.name))
        self.commands = []
        self.web = LocalWeb(self.service, self.commands.append, port=0)
        self.addCleanup(self.web.close)

    def test_static_state_and_reject_cross_origin_mutation(self):
        response = requests.get(self.web.url, timeout=5)
        self.assertEqual(response.status_code, 200)
        self.assertIn('Схема убежища', response.text)
        token = requests.get(self.web.url+'/api/state', timeout=5).json()['token']
        url = self.web.url+'/api/action'
        self.assertEqual(requests.post(url, json={'action': 'publish'}, timeout=5).status_code, 403)
        headers = {'X-ItemSniper-Token': token, 'Origin': 'https://untrusted.example'}
        self.assertEqual(requests.post(url, headers=headers, json={'action': 'publish'}, timeout=5).status_code, 403)
        headers['Origin'] = self.web.url
        self.assertEqual(requests.post(url, headers=headers, json={'action': 'publish'}, timeout=5).status_code, 200)
        self.assertEqual(self.commands, ['publish'])

    def test_path_traversal_and_invalid_host_rejected(self):
        response = requests.get(self.web.url+'/api/state', headers={'Host': 'evil.example'}, timeout=5)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(requests.get(self.web.url+'/%2e%2e/core.py', timeout=5).status_code, 404)

    def test_web_calibration_and_html_import(self):
        self.service.setup_frame={'left':-1920,'top':0,'width':1920,'height':1080,'at':1}
        headers={'Origin':self.web.url,'X-ItemSniper-Token':self.web.token}
        rectangle={'x':100,'y':50,'width':400,'height':500}
        response=requests.post(self.web.url+'/api/region',headers=headers,json={'kind':'loot','rectangle':rectangle},timeout=5)
        self.assertEqual(response.status_code,200)
        self.assertEqual(self.service.state.value['regions']['loot']['left'],-1820)
        rectangle['width']=2000
        self.assertEqual(requests.post(self.web.url+'/api/region',headers=headers,json={'kind':'loot','rectangle':rectangle},timeout=5).status_code,400)
        self.assertEqual(self.service.state.value['regions']['loot']['width'],400)
        html='<html><body>Hideout</body></html>'
        response=requests.post(self.web.url+'/api/wiki-html',headers=headers,json={'html':html},timeout=5)
        self.assertEqual(response.status_code,200)
        self.assertEqual(self.commands,[{'action':'import_html','html':html}])

    def test_quest_routes_and_progress_validation(self):
        from itemsniper.progression import QuestProgress
        self.service.set_catalog({'items':[{'id':'i','name':'Bolts'}]})
        self.service.quest_progress=QuestProgress([{'id':'q','name_ru':'Задание','name_en':'Task','kind':'side','objectives':[{'id':'o','count':2,'type':'giveItem','items':['i']}],'taskRequirements':[]}],self.service.state.value)
        headers={'Origin':self.web.url,'X-ItemSniper-Token':self.web.token}
        result=requests.get(self.web.url+'/api/quests',timeout=5).json()
        self.assertEqual(result['total'],1)
        result=requests.get(self.web.url+'/api/quest?id=q',timeout=5).json()
        self.assertIn('i',result['items'])
        response=requests.post(self.web.url+'/api/quest',headers=headers,json={'id':'q','status':'active'},timeout=5)
        self.assertEqual(response.status_code,200)
        self.assertIn('Bolts',self.service.quest_progress.targets(self.service.records))
        response=requests.post(self.web.url+'/api/quest',headers=headers,json={'id':'q','objectives':{'o':{'count':2,'done':True}}},timeout=5)
        self.assertEqual(response.status_code,200)
        self.assertEqual(self.service.quest_progress.targets(self.service.records),{})
        self.assertEqual(requests.post(self.web.url+'/api/quest',headers=headers,json={'id':'q','status':'bad'},timeout=5).status_code,400)


if __name__ == '__main__':
    unittest.main()
