"""First detections after opening the supplied inventory and storage windows."""
import json,time,re
from pathlib import Path
from PIL import Image
from tests.benchmark_new_items import Replay
from itemsniper.reveal import RevealLane
from itemsniper.library import VisualLibrary
from itemsniper.vision import overlap


def main():
    c=json.loads(Path('data/catalog.json').read_text(encoding='utf8'));live=Replay()
    lane=RevealLane(live,VisualLibrary(Path('data')),lambda:c,lambda:True,lambda s:None)
    while not lane.ready and not lane.error:time.sleep(.01)
    specs=[('toolbox','43f7520d-0d8d-47cb-946d-9efdf20b29fe',[
        ('Bolts',(1262,79,64,64)),('Poxeram',(1326,79,64,64)),('Silicone',(1390,79,64,64)),
        ('Sb.3 5-shot',(788,167,67,65)),('Sb.3 5-shot',(858,167,67,65))]),
        ('cases','98d4b62c-f056-441a-854a-902a3146f74b',[
        ('wires',(196,63,64,64)),('Shustrilo',(1530,63,192,64)),('Fleece',(196,505,64,128))])]
    rows=[]
    for sequence,(name,key,targets) in enumerate(specs,1):
        live.frame=None;time.sleep(.5);live.results=[];live.tracker.tracks=[]
        image=Image.open(Path.home()/f'AppData/Local/Temp/codex-clipboard-{key}.png').convert('RGB')
        start=time.perf_counter();live.frame={'image':image,'sequence':sequence,'at':time.time()};found={}
        while time.perf_counter()-start<8 and not lane.error:
            for i,(item,box) in enumerate(targets):
                if i in found:continue
                matches=[at for at,hit in live.results if re.search(item,hit['name'],re.I) and overlap(box,hit['box'])>.6]
                if matches:found[i]=round((min(matches)-start)*1000,1)
            if len(found)==len(targets):break
            time.sleep(.002)
        row={'opening':name,'found_ms':found,'targets':targets,'error':lane.error};rows.append(row);print(row,flush=True)
    live.frame=None;lane.close();lane.thread.join(5)
    Path('data/new-item-opening-benchmark.json').write_text(json.dumps(rows,indent=2),encoding='utf8')
    assert all(len(row['found_ms'])==len(row['targets']) for row in rows)


if __name__=='__main__':main()
