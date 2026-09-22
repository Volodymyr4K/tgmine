import sys,json,glob,random,statistics as st
sys.path.insert(0,'.')
from datetime import datetime
from tgmine import routes as RT
H=RT.hav
random.seed(1)
def onsets(ev,quiet_min,R=20):
    out=[]; last=[]
    for e in sorted(ev,key=lambda e:e['_dt']):
        recent=[x for x in last if (e['_dt']-x['_dt']).total_seconds()<=quiet_min*60 and H((x['lat'],x['lon']),(e['lat'],e['lon']))<R]
        if not recent: out.append(e)
        last.append(e)
    return out
tot=[]
for f in sorted(glob.glob(sys.argv[1]+'/raids/*.json')):
    r=json.load(open(f))
    ev=[e for e in r['events'] if e.get('lat') and e.get('geo_conf') not in('centroid','region-snap') and not e.get('dup_of') and e.get('kind') in('фіксація','ППО','збиття','вибух','тривога')]
    for e in ev: e['_dt']=datetime.fromisoformat(e['t'])
    vec=[v for v in r['vectors'] if v.get('dst') and v.get('src') and H(tuple(v['src']),tuple(v['dst']))>15]
    def conf(evs,lo=5,hi=120,R=25):
        n=0
        for v in vec:
            t=datetime.fromisoformat(v['t'])
            if any(lo*60<=(e['_dt']-t).total_seconds()<=hi*60 and H((e['lat'],e['lon']),tuple(v['dst']))<R for e in evs): n+=1
        return n
    row=[r['date'],len(vec)]
    for q in (0,60,120):
        on=onsets(ev,q) if q else ev
        n=conf(on)
        nulls=[]
        for k in range(30):
            ts=[e['_dt'] for e in on]; random.shuffle(ts)
            nulls.append(conf([dict(e,_dt=t) for e,t in zip(on,ts)]))
        m=st.mean(nulls); sd=st.pstdev(nulls) or 1
        row.append(f"quiet{q}: pts {len(on)} hit {n} null {m:.1f} z {(n-m)/sd:+.1f}")
    print(*row)
