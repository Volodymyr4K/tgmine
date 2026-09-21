"""Зібрати сховище поточним кодом у довільну теку — для А/Б без чіпання store/. Див. README."""
import json, sys, shutil
from datetime import datetime
from pathlib import Path
sys.path.insert(0, '.')
from tgmine import store as ST, extract as E, geocode as GC
root = Path(sys.argv[1])
if root.exists(): shutil.rmtree(root)
first = ST.Store().dates()[0]          # вікно — як у справжньому --rebuild
cfg = E.Config.load('configs/ru-monitor.yaml')
gaz = GC.Gazetteer.load('gazetteer/RU.txt', 'gazetteer/UA.txt')
targets = json.load(open('targets.json', encoding='utf-8'))
posts = []
for ch in ('lpr1_treugolnik', 'kupolrussia', 'vrv_radar', 'locatorru'):  # як CHANNELS у sync.py
    posts += [json.loads(l) for l in open(f'data/{ch}.jsonl', encoding='utf-8') if l.strip()]
posts = [p for p in posts if datetime.fromisoformat(p['date']).astimezone(ST.MSK).strftime('%Y-%m-%d') >= first]
n = ST.Store(root=str(root)).build(posts, cfg, gaz, log=lambda *a: None, targets=targets)
print('подій', n, '->', root)
