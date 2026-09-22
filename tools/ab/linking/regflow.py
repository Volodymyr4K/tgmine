import json,glob,sys,random,statistics as st,collections
sys.path.insert(0,'.'); sys.path.insert(0,'tools/ab')
from datetime import datetime
import geo_cmp as G
random.seed(13)
def reg(lat,lon):
    for k,rings in G.REG.items():
        if any(G._in_ring(lat,lon,r) for r in (rings if isinstance(rings[0][0],list) else [rings])): return k
    return None
def J(F,lo,hi):
    return sum(1 for a in F for b in F if a is not b and a['d']==b['s'] and lo<(b['t']-a['t']).total_seconds()/60<=hi)
for f in sorted(glob.glob(sys.argv[1]+'/raids/*.json')):
    r=json.load(open(f))
    F=[]
    for v in r['vectors']:
        if not(v.get('src') and v.get('dst')): continue
        s=reg(*v['src']); d=reg(*v['dst'])
        if s and d and s!=d: F.append({'s':s,'d':d,'t':datetime.fromisoformat(v['t'])})
    fl=collections.Counter((x['s'],x['d']) for x in F)
    row=[r['date'],'region-crossing vectors',len(F),'distinct flows',len(fl)]
    for lo,hi in ((0,240),(-240,0)):
        n=J(F,lo,hi); N=[]
        for k in range(200):
            ts=[x['t'] for x in F]; random.shuffle(ts); N.append(J([dict(x,t=t) for x,t in zip(F,ts)],lo,hi))
        m=st.mean(N); sd=st.pstdev(N) or 1
        row.append(f'joints[{lo},{hi}] {n} null {m:.1f} z {(n-m)/sd:+.1f}')
    print(*row); print('    top flows',fl.most_common(6))
