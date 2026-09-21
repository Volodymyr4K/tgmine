"""А/Б двох сховищ: пари за спільним id, рядок-до-рядка."""
import json, glob, sys, collections, random
sys.path.insert(0, '.')
from tgmine.geocode import haversine
def load(root):
    d = {}
    for f in sorted(glob.glob(f'{root}/events/*.jsonl')):
        for l in open(f, encoding='utf-8'):
            if l.strip():
                e = json.loads(l); d[e['id']] = e
    return d
A, B = load(sys.argv[1]), load(sys.argv[2])
com = A.keys() & B.keys()
print(f'спільних {len(com)} | лише в А {len(A.keys()-B.keys())} | лише в Б {len(B.keys()-A.keys())}')
uniq = lambda e: not e.get('dup_of') and not e.get('noise')
c = collections.Counter(); ex = collections.defaultdict(list)
for i in sorted(com):
    a, b = A[i], B[i]
    if not uniq(b): continue
    for k in ('kind', 'scope', 'utype', 'geo_conf'):
        if a.get(k) != b.get(k):
            key = (k, a.get(k), b.get(k)); c[key] += 1
            if len(ex[key]) < 3: ex[key].append((b.get('place'), (b.get('text') or '')[:95]))
    if a.get('lat') and b.get('lat'):
        d = haversine((a['lat'], a['lon']), (b['lat'], b['lon']))
        if d > 5:
            key = ('рух>5км', a.get('kind'), b.get('kind')); c[key] += 1
            if len(ex[key]) < 4: ex[key].append((f"{a.get('place')} -> {b.get('place')} {d:.0f}км", (b.get('text') or '')[:80]))
    elif bool(a.get('lat')) != bool(b.get('lat')):
        c[('координата', bool(a.get('lat')), bool(b.get('lat')))] += 1
for k, v in sorted(c.items(), key=lambda kv: -kv[1]):
    print(f'  {v:6}  {k}')
    for pl, t in ex[k]: print(f'            [{pl}] {t}')
def launch_stat(D, name):
    pts = [e for e in D.values() if uniq(e) and e['kind'] == 'пуск' and e['scope'] == 'точка' and e.get('lat')]
    on = sum(1 for e in pts if e.get('depth') == 0)
    allp = sum(1 for e in D.values() if uniq(e) and e['kind'] == 'пуск')
    print(f'{name}: пусків {allp}, з них крапок {len(pts)}; на підконтрольній Україні (арбітр) {on} = {on/max(len(pts),1):.0%}')
launch_stat(A, 'А'); launch_stat(B, 'Б')
