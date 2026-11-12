"""Integration evaluation against the entire catalog index, with recorded local OCR."""
import json
import time
from pathlib import Path
import numpy as np
from PIL import Image
from itemsniper.library import VisualLibrary
from itemsniper.vision import Vision

directory=Path('data')
vision=Vision()
vision.library=VisualLibrary(directory)
catalog=json.loads((directory/'catalog.json').read_text(encoding='utf-8'))
rows=[]
for stamp in ('223416','223447','224755'):
    data=json.loads((directory/'frame-validation'/f'{stamp}-ocr.json').read_text(encoding='utf-8'))
    image=Image.open(data['file']).convert('RGB').crop((1226,48,1919,949))
    lines=[(line['text'],line['score'],np.array(line['box'])) for line in data['text']]
    vision.text=lambda image,lines=lines:lines
    start=time.perf_counter()
    hits=vision.items(image,catalog)
    row={'frame':stamp,'seconds_without_ocr':round(time.perf_counter()-start,3),
         'indexed':vision.library.status['indexed'],'hits':hits,'analysis':vision.last_analysis}
    rows.append(row)
    print(stamp,row['seconds_without_ocr'],[(h['name'],h.get('ambiguous',False)) for h in hits],flush=True)
(directory/'frame-validation'/'full-library-results.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
