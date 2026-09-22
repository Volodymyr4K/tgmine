import json,glob,sys,random,statistics as st,collections
sys.path.insert(0,'.'); sys.path.insert(0,'mapper')
from datetime import datetime,timedelta
from tgmine import routes as RT
import mkreglabels as RL
REG=json.load(open('regions.json'))
def mins(h):
    hh,mm=map(int,h.split(':')); return (hh+24 if hh<12 else hh)*60+mm
def stubs(r):
    out=[]
    for e in r['events']:
        legs=e.get('legs') or []
        dst_of={(round(g[5],4),round(g[6],4)):g for g in legs}
        for g in legs:
            sn,sla,slo,sar,dn,dla,dlo,dar=g
            if not dar or dn not in REG: continue
            seen=set()
            while (round(sla,4),round(slo,4)) in dst_of and (sla,slo) not in seen:
                seen.add((sla,slo)); p=dst_of[(round(sla,4),round(slo,4))]
                if p[3]: break
                sn,sla,slo,sar=p[0],p[1],p[2],p[3]
            if sar: continue
            if any(RL.inside(sla,slo,rg) for rg in REG[dn]): continue
            out.append({'t':mins(e['hhmm']),'xy':(sla,slo),'R':dn})
    return out
def cands(r,kind):
    if kind=='routes':
        rs,_=RT.build(r)
        return [{'t':mins(ro['pts'][0]['hhmm']),'xy':(ro['pts'][0]['la'],ro['pts'][0]['lo'])} for ro in rs if ro['pts'] and ro['pts'][0].get('hhmm')]
    return [{'t':mins(e['hhmm']),'xy':(e['lat'],e['lon'])} for e in r['events'] if e.get('scope')=='точка' and e.get('kind') in('фіксація','ППО','збиття','вибух') and e.get('geo_conf') not in('centroid','region-snap')]
def bridges(S,C,sign=1):
    n=amb=0
    for s in S:
        rings=REG[s['R']]; ok=[]
        for c in C:
            dt=(c['t']-s['t'])*sign
            if not(10<=dt<=240): continue
            if not any(RL.inside(c['xy'][0],c['xy'][1],rg) for rg in rings): continue
            d=RT.hav(s['xy'],c['xy']); v=d/(dt/60)
            if 60<=v<=250: ok.append((abs(v-160)/160+dt/240,c))
        if ok:
            n+=1; ok.sort(key=lambda x:x[0])
            if len(ok)>1 and ok[1][0]-ok[0][0]<0.1: amb+=1
    return n,amb
for kind in ('routes','fix'):
    T=[0,0,0,0,0,0]
    for f in sorted(glob.glob(sys.argv[1]+'/raid_*.json')):
        r=json.load(open(f)); S=stubs(r); C=cands(r,kind)
        for c in C: pass
        # inside cache
        n,amb=bridges(S,C); nb,_=bridges(S,C,-1)
        N=[]
        rng=random.Random(1)
        for k in range(20):
            ts=[c['t'] for c in C]; rng.shuffle(ts); N.append(bridges(S,[dict(c,t=t) for c,t in zip(C,ts)])[0])
        T=[T[0]+len(S),T[1]+n,T[2]+amb,T[3]+nb,T[4]+st.mean(N),T[5]]
        print(kind,f[-15:-5],'обрубків',len(S),'продовження',n,'неоднозн.',amb,'назад у часі',nb,'випадково',round(st.mean(N),1))
    print('РАЗОМ',kind,'обрубків',T[0],'продовжень',T[1],'неоднозначних',T[2],'назад',T[3],'випадково',round(T[4],1))
