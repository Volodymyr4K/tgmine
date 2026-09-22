import json,sys
from natasha import Segmenter, NewsEmbedding, NewsNERTagger, Doc
seg=Segmenter(); ner=NewsNERTagger(NewsEmbedding())
T=[json.loads(l) for l in open(sys.argv[1])]
L={json.loads(l)['i']:json.loads(l) for l in open(sys.argv[2])}
hit=tot=junk=0
for x in T[:100]:
    d=Doc(x['text'].replace(' / ','\n')); d.segment(seg); d.tag_ner(ner)
    locs=[s.text for s in d.spans if s.type=='LOC']
    miss=L[x['i']]['missed']
    for m in miss:
        tot+=1; hit+= any(m.split()[0][:5].lower() in l.lower() for l in locs)
    if x['i']<25: print(x['i'],x['text'][:90],'->',locs)
print('missed places recovered by natasha LOC',hit,'of',tot)
