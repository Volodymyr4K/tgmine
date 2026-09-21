"""Поіменно: які пуски підсвітить редактор у ніч — і що в їхніх текстах."""
import json, subprocess, sys, os, collections
for d in sys.argv[1:]:
    subprocess.run([sys.executable, 'raid.py', d], capture_output=True)
    out = f'/tmp/night_{d}.js'
    subprocess.run([sys.executable, 'mapper/mknight.py', f'raid_{d}.json', out], capture_output=True)
    raid = json.load(open(f'raid_{d}.json', encoding='utf-8'))
    byurl = {e.get('url'): e for e in raid['events']}
    s = open(out, encoding='utf-8').read(); n = json.loads(s[s.index('=')+1:].rstrip().rstrip(';'))
    L = [x for x in n['sightings'] if max((x.get('kinds') or {'-':0}).items(), key=lambda kv: kv[1])[0] == 'пуск']
    print(f'\n=== ніч {d}: місць {len(n["sightings"])}, підсвічених пусків {len(L)} ===')
    for x in L:
        txt = [(byurl.get(s_['u']) or {}).get('text', '')[:110] for s_ in x.get('src', []) if s_.get('k') == 'пуск'][:2]
        print(f'  [{x["place"]} · {x.get("area") or "крапка"} · {dict(x.get("types") or {})}]')
        for t_ in txt: print(f'        {t_}')
    os.remove(f'raid_{d}.json')
