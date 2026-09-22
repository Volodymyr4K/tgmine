import json,glob,sys,random,statistics as st
sys.path.insert(0,'.')
from tgmine import routes as RT
H=RT.hav; TN=RT.turn
random.seed(11)
def cnt(hops):
    ok=fast=0
    for a in hops:
        for b in hops:
            if a is b: continue
            dt=(b['dt']-a['dt']).total_seconds()/60
            if not(0<dt<=240) or H(a['dst'],b['src'])>30 or TN(a['brg'],b['brg'])>70: continue
            v=H(a['dst'],b['dst'])/(dt/60)
            if RT.V_MIN<=v<=RT.V_MAX: ok+=1
            else: fast+=1
    return ok,fast
tot=[0,0,0,0]
for f in sorted(glob.glob(sys.argv[1]+'/raids/*.json')):
    r=json.load(open(f))
    for v in r['vectors']: v.setdefault('hhmm',v['t'][11:16])
    hops,_=RT._hops(r['vectors'],{e.get('url'):e.get('region') for e in r['events'] if e.get('url')},r.get('region_geo'))
    ok,fast=cnt(hops); N=[]
    for k in range(200):
        ts=[h['dt'] for h in hops]; random.shuffle(ts); N.append(cnt([dict(h,dt=t) for h,t in zip(hops,ts)]))
    mo=st.mean(x[0] for x in N); mf=st.mean(x[1] for x in N)
    so=st.pstdev([x[0] for x in N]) or 1; sf=st.pstdev([x[1] for x in N]) or 1
    tot=[tot[0]+ok,tot[1]+mo,tot[2]+fast,tot[3]+mf]
    print(r['date'],f"speed-ok {ok} null {mo:.1f} z {(ok-mo)/so:+.1f} | speed-reject {fast} null {mf:.1f} z {(fast-mf)/sf:+.1f}")
print('total speed-ok',tot[0],'null',round(tot[1],1),'| speed-reject',tot[2],'null',round(tot[3],1))
