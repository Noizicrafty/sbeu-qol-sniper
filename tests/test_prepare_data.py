import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


class PrepareDataTests(unittest.TestCase):
    def test_clean_checkout_initializes_references_and_preserves_existing_profile(self):
        source=Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'scripts').mkdir();(root/'reference').mkdir()
            shutil.copy2(source/'scripts/prepare_data.py',root/'scripts/prepare_data.py')
            for name,value in [('catalog.json',{'items':[{'name':'Bolts'}]}),('progression.json',{'tasks':[{'id':'demo'}]})]:
                (root/'reference'/name).write_text(json.dumps(value),encoding='utf8')
            command=[sys.executable,str(root/'scripts/prepare_data.py')]
            subprocess.run(command,cwd=root,check=True,capture_output=True)
            self.assertEqual(json.loads((root/'data/catalog.json').read_text())['items'][0]['name'],'Bolts')
            self.assertEqual(json.loads((root/'data/progression.json').read_text())['tasks'][0]['id'],'demo')
            profile=root/'data/state.json';profile.write_text('{"keep":"personal progress"}',encoding='utf8')
            catalog=root/'data/catalog.json';catalog.write_text('{"keep":"existing catalog"}',encoding='utf8')
            before=(profile.read_bytes(),catalog.read_bytes())
            subprocess.run(command,cwd=root,check=True,capture_output=True)
            self.assertEqual(before,(profile.read_bytes(),catalog.read_bytes()))


if __name__=='__main__':unittest.main()
