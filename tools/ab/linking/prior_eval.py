import json,glob,collections,math,random,sys
sys.path.insert(0,'.')
from datetime import datetime
from tgmine.geocode import haversine as H
C=0.5
def cell(la,lo): return (round(la/C),round(lo/C))
N=collections.defaultdict(list); OBS=collections.defaultdict(list)
for f in sorted(glob.glob('store/events/*.jsonl')):
    d=f[-16:-6]
    for l in open(f):
        e=json.loads(l)
        if e.get('dup_of') or e.get('noise'): continue
        t=datetime.fromisoformat(e['t']).timestamp()/60
        for g in e.get('legs') or []:
            if not g[3] and not g[7]: N[d].append((t,(g[1],g[2]),(g[5],g[6])))
        if e.get('scope')=='точка' and e.get('lat') and e.get('geo_conf') not in('centroid','region-snap') and e['kind'] in('фіксація','ППО','збиття','вибух'):
            OBS[d].append((t,(e['lat'],e['lon'])))
days=sorted(N)
trans=collections.Counter(); out=collections.Counter()
per=collections.defaultdict(collections.Counter)
for d in days:
    for t,a,b in set((0,x,y) for _,x,y in N[d]):
        per[d][(cell(*a),cell(*b))]+=1
for d in days:
    for k,v in per[d].items(): trans[k]+=v; out[k[0]]+=v
def prior(a,c,d):
    ca,cc=cell(*a),cell(*c)
    k=(ca,cc)
    n=trans[k]-per[d][k]
    # сусідні клітинки цілі теж рахуються (згладжування)
    nb=sum(trans[(ca,(cc[0]+dx,cc[1]+dy))]-per[d][(ca,(cc[0]+dx,cc[1]+dy))] for dx in(-1,0,1) for dy in(-1,0,1))
    tot=out[ca]-sum(per[d][x] for x in per[d] if x[0]==ca)
    return math.log((n+0.3*nb+0.1)/(tot+10))
rng=random.Random(1)
R=collections.Counter()
for d in days[20:]:
    obs=OBS[d]
    for t,a,b in N[d]:
        cands=[(tc,c) for tc,c in obs if 10<=tc-t<=180 and 5<H(a,c)<350]
        cands=[(tc,c) for tc,c in cands if 60<=H(a,c)/((tc-t)/60)<=250]
        if len(cands)<2: continue
        # має існувати кандидат біля B, інакше задача не має відповіді
        if not any(H(c,b)<40 for _,c in cands): continue
        R['задач']+=1
        best=max(cands,key=lambda x:prior(a,x[1],d)-abs(H(a,x[1])/((x[0]-t)/60)-160)/160)
        R['пам\'ять коридорів']+= H(best[1],b)<40
        near=min(cands,key=lambda x:x[0]-t)
        R['найближча в часі']+= H(near[1],b)<40
        rnd=rng.choice(cands)
        R['випадковий']+= H(rnd[1],b)<40
        R['кандидатів_сума']+=len(cands)
n=R['задач']
print('задач',n,'середньо кандидатів',round(R['кандидатів_сума']/n,1))
for k in ("пам'ять коридорів","найближча в часі","випадковий"): print(f'  {k}: {R[k]/n:.0%}')
