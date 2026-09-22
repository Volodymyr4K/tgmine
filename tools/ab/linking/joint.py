import json,glob,random,statistics as st,sys
sys.path.insert(0,'.')
from datetime import datetime
from tgmine import routes as RT
H=RT.hav; B=RT.bearing; TN=RT.turn
random.seed(7)
def joints(V,lo,hi,turnmax=None):
    n=0
    for a in V:
        for b in V:
            if a is b: continue
            dt=(b['_t']-a['_t']).total_seconds()/60
            if not(lo<=dt<=hi): continue
            if H(tuple(a['dst']),tuple(b['src']))>30: continue
            if turnmax and TN(B(tuple(a['src']),tuple(a['dst'])),B(tuple(b['src']),tuple(b['dst'])))>turnmax: continue
            n+=1
    return n
for f in sorted(glob.glob(sys.argv[1]+'/raids/*.json')):
    r=json.load(open(f))
    V=[v for v in r['vectors'] if v.get('src') and v.get('dst') and H(tuple(v['src']),tuple(v['dst']))>15]
    for v in V: v['_t']=datetime.fromisoformat(v['t'])
    row=[r['date'],len(V)]
    for lo,hi,tm in ((0,240,None),(0,240,70),(-240,0,None)):
        n=joints(V,lo,hi,tm); nulls=[]
        for k in range(100):
            ts=[v['_t'] for v in V]; random.shuffle(ts)
            nulls.append(joints([dict(v,_t=t) for v,t in zip(V,ts)],lo,hi,tm))
        m=st.mean(nulls); sd=st.pstdev(nulls) or 1
        row.append(f"[{lo},{hi}] turn{tm}: {n} null {m:.1f} z {(n-m)/sd:+.1f}")
    print(*row)
