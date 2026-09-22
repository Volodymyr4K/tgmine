import json,glob,sys,random,statistics as st
sys.path.insert(0,'.'); sys.path.insert(0,'mapper')
exec(open(sys.argv[2]).read().split("def bridges")[0])
def anchor(R):
    rings=REG[R]; return RL.anchor(max(rings,key=RL.area))
ANC={}
def bridges(S,C,cone,vmin,vmax,tmax,unique):
    n=0
    for s in S:
        if s['R'] not in ANC: ANC[s['R']]=anchor(s['R'])
        a=ANC[s['R']]; brg=RT.bearing(s['xy'],tuple(a)); ok=[]
        for c in C:
            dt=c['t']-s['t']
            if not(15<=dt<=tmax): continue
            if not any(RL.inside(c['xy'][0],c['xy'][1],rg) for rg in REG[s['R']]): continue
            if RT.turn(brg,RT.bearing(s['xy'],c['xy']))>cone: continue
            d=RT.hav(s['xy'],c['xy']); v=d/(dt/60)
            if vmin<=v<=vmax: ok.append(c)
        if ok and (not unique or len(ok)==1): n+=1
    return n
RS={}
for f in sorted(glob.glob(sys.argv[1]+'/raid_*.json')):
    r=json.load(open(f)); RS[f]=(stubs(r),cands(r,'routes'))
for cone,vmin,vmax,tmax,uniq in ((180,60,250,240,False),(30,60,250,240,False),(30,100,220,180,False),(20,100,220,150,True),(30,100,220,180,True)):
    n=z=0
    for f,(S,C) in RS.items():
        n+=bridges(S,C,cone,vmin,vmax,tmax,uniq)
        rng=random.Random(1); N=[]
        for k in range(20):
            ts=[c['t'] for c in C]; rng.shuffle(ts); N.append(bridges(S,[dict(c,t=t) for c,t in zip(C,ts)],cone,vmin,vmax,tmax,uniq))
        z+=st.mean(N)
    print(f'конус ±{cone}° v {vmin}-{vmax} ≤{tmax}хв {"лише єдиний" if uniq else ""}: містків {n}, випадково {z:.1f}, оцінка справжніх {max(0,n-z):.0f} ({max(0,n-z)/max(n,1):.0%})')
