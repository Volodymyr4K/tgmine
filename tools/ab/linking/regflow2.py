"""Чесний нуль-тест потоків між областями (виправлення §16.8 після рецензії):
без dup_of; повтори (канал, A, B) у межах 60 хв -> одна заява; рахуються
РІЗНІ трійки A->B->C (не пари); перемішування часу блоками всередині каналу."""
import json,glob,sys,random,statistics as st,collections
sys.path.insert(0,'.'); sys.path.insert(0,'tools/ab')
from datetime import datetime
import geo_cmp as G
def reg(lat,lon):
    for k,rings in G.REG.items():
        if any(G._in_ring(lat,lon,r) for r in rings): return k
def triples(F,lo,hi):
    out=set()
    for a in F:
        for b in F:
            if a is not b and a['d']==b['s'] and b['d']!=a['s'] and lo<(b['t']-a['t']).total_seconds()/60<=hi: out.add((a['s'],a['d'],b['d']))
    return len(out)
rows=[]
for f in sorted(glob.glob(sys.argv[1]+'/*.json')):
    r=json.load(open(f))
    dup={e['url'] for e in r['events'] if e.get('dup_of')}
    ch={e['url']:e['channel'] for e in r['events']}
    F=[]; last={}
    for v in sorted(r['vectors'],key=lambda v:v['t']):
        if v['url'] in dup or not(v.get('src') and v.get('dst')): continue
        s=reg(*v['src']); d=reg(*v['dst'])
        if not s or not d or s==d: continue
        t=datetime.fromisoformat(v['t']); key=(ch.get(v['url']),s,d)
        if key in last and (t-last[key]).total_seconds()<=3600: continue
        last[key]=t; F.append({'s':s,'d':d,'t':t,'c':ch.get(v['url'])})
    if len(F)<3: rows.append((r['date'],len(F),0,0,0)); continue
    n=triples(F,0,240); nb=triples(F,-240,0); N=[]
    rng=random.Random(1)
    for k in range(300):
        G2=[]
        for c in {x['c'] for x in F}:
            xs=[x for x in F if x['c']==c]; ts=[x['t'] for x in xs]; rng.shuffle(ts)
            G2+=[dict(x,t=t) for x,t in zip(xs,ts)]
        N.append(triples(G2,0,240))
    m=st.mean(N); sd=st.pstdev(N) or 1
    p=sum(1 for x in N if x>=n)/len(N)
    rows.append((r['date'],len(F),n,round(m,1),round((n-m)/sd,1),nb,p))
    print(*rows[-1])
