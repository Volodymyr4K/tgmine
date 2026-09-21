"""Поіменна перевірка пусків у сховищі: де крапка і чи це джерело."""
import json, glob, re, sys, collections
root = sys.argv[1]
ev = []
for f in sorted(glob.glob(f'{root}/events/*.jsonl')):
    for l in open(f, encoding='utf-8'):
        if l.strip(): ev.append(json.loads(l))
L = [e for e in ev if e['kind'] == 'пуск' and not e.get('dup_of') and not e.get('noise')]
pts = [e for e in L if e['scope'] == 'точка' and e.get('lat')]
area = [e for e in L if e['scope'] != 'точка']
on = [e for e in pts if e.get('depth') == 0]
off = [e for e in pts if e.get('depth') != 0]
print(f'пусків {len(L)}: крапок {len(pts)} (на підконтрольній Україні {len(on)} = {len(on)/max(len(pts),1):.0%}), без крапки {len(area)}')
print(f'крапки за geo_conf: {collections.Counter(e.get("geo_conf") for e in pts).most_common()}')
def show(title, rows, n):
    print(f'\n--- {title} ({len(rows)}) ---'); seen = set()
    for e in rows:
        k = (e.get('text') or '')[:60]
        if k in seen: continue
        seen.add(k); print(f'  [{e.get("place")} · {e.get("utype")} · гл.{e.get("depth")}] {(e.get("text") or "")[:115]}')
        if len(seen) >= n: break
show('крапка НЕ на підконтрольній Україні — усі різні', off, 60)
SRC = re.compile(r'\b(от|из-под|из района|с района|со стороны)\s+[А-ЯЁ]', re.I)
fn = [e for e in area if SRC.search(e.get('text') or '')]
show('без крапки, хоча є «от/из-под X» — можливо, загублене джерело', fn, 40)
show('крапка на підконтрольній Україні — вибірка', on[::max(1, len(on)//25)], 25)
