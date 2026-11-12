import json
from pathlib import Path
from PIL import Image
from .core import save_json
from .service import Service
from .library import VisualLibrary
from .vision import Vision
from .webserver import LocalWeb,STATIC

def run(directory):
    import dxcam
    camera=dxcam.create(output_color='RGB')
    try:camera.grab()
    finally:camera.release()
    service=Service(directory);library=VisualLibrary(directory)
    vision=Vision();vision.library=library;vision.prepare_caption_ocr()
    empty=Image.new('RGB',(320,240))
    assert vision.items(empty,service.catalog,fast=True)==[]
    # Load detector/classifier models as well; first use must work offline in the bundle.
    vision.text(empty)
    from .reveal import RevealDetector
    reveal=RevealDetector(library);reveal.prepare()
    assert reveal.recognize(empty,(0,0,192,192),service.catalog,64,lambda *args:None)==[]
    import tkinter as tk
    from .overlay import ScreenOverlay
    root=tk.Tk();root.withdraw();overlay=ScreenOverlay(root);root.update_idletasks();overlay.native_styles()
    web=LocalWeb(service,lambda action:None,port=0)
    try:
        import requests
        state=requests.get(web.url+'/api/state',timeout=10).json()
        assert requests.get(web.url+'/quests.js',timeout=10).ok
        assert requests.get(web.url,timeout=10).text.find('SBEU qol sniper')>=0
        result={'ok':True,'dxgi_ready':True,'new_item_lane':True,'items':len(service.records),'quests':len(service.quest_progress.tasks),
                'indexed':library.status['indexed'],'root_hidden':root.state()=='withdrawn','overlay_excluded':overlay.excluded_from_capture,
                'models_ready':vision.caption_ready,'ui_assets':(STATIC/'quests.js').exists(),'state_served':state['quest_count']>0}
        save_json(directory/'self-test.json',result)
    finally:web.close();overlay.close();root.destroy()
