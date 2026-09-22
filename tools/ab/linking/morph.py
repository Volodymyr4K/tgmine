import sys,pickle,re,collections,random
sys.path.insert(0,'.')
import pymorphy3
from tgmine import geocode as GC
import sync
M=pymorphy3.MorphAnalyzer()
gaz=GC.Gazetteer.load(*sync.GAZ)
posts=pickle.load(open(sys.argv[1],'rb'))
RX=re.compile(r"\b(?:в сторону|в направлении|на|от|из-под|через|до|курсом на|далее на)\s+(?:г\.\s*)?([А-ЯЁ][а-яё]+(?:-[А-ЯЁа-яё][а-яё]+)*)")
forms=collections.Counter()
for p in posts:
    for m in RX.finditer(p['text']): forms[m.group(1)]+=1
C=collections.Counter(); ex=collections.defaultdict(list)
for w,n in forms.most_common(1500):
    q=GC.norm(w)
    exact=bool(gaz.by_name.get(q))
    stem=gaz.candidates(w)
    ps=M.parse(w)
    geo=[x for x in ps if 'Geox' in x.tag]
    best=(geo or ps)[0]
    nom=best.inflect({'nomn'})
    nomw=nom.word if nom else best.normal_form
    # for adjectives keep gender? use normal_form of Geox
    cand=[best.normal_form, nomw]
    mhit=[c for c in cand if gaz.by_name.get(GC.norm(c))]
    k=('exact' if exact else 'noexact')+'|'+('stemhit' if stem else 'stemmiss')+'|'+('morphhit' if mhit else 'morphmiss')
    C[k]+=n
    if len(ex[k])<8: ex[k].append((w,n,best.normal_form,'Geox' if geo else '', [s.get('name') for s in stem[:2]]))
tot=sum(C.values())
for k,v in C.most_common(): print(k,v,f'{v/tot:.1%}')
for k in ex:
    if 'noexact' in k: print(k,ex[k])
