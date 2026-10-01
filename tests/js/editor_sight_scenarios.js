// Мітки зведення фіксацій за період: порядок малювання, вибір, видалення.
// Сценарії в живому редакторі; потрібні ночі (nights/index.json), тож у pytest
// не входить. Запуск (gstack browse, вікно 1600x1000):
//   browse goto http://127.0.0.1:<порт>/editor.html?v=$(date +%s)   # зачекати ~8 с
//   browse eval tests/js/editor_sight_scenarios.js                  # зачекати ~25 с
//   browse eval <файл із `(()=>JSON.stringify(window.__res,null,1))()`>
// Усі рядки мають починатись з «ok». Сценарій міняє обʼєкти на екрані — на
// робочій карті не запускати.
(()=>{
const R=[], ok=(name,cond,extra)=>R.push((cond?'ok   ':'FAIL ')+name+(cond?'':' :: '+JSON.stringify(extra)));
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
window.confirm=()=>true;
const cv=document.querySelector('canvas');
const ev=(type,x,y,extra)=>{ const r=cv.getBoundingClientRect();
  cv.dispatchEvent(new PointerEvent(type,Object.assign({clientX:r.left+x,clientY:r.top+y,button:0,buttons:1,bubbles:true,pointerId:1},extra||{}))); };
const click=(x,y,extra)=>{ ev('pointerdown',x,y,extra); ev('pointerup',x,y,extra); };
const key=k=>document.dispatchEvent(new KeyboardEvent('keydown',{key:k,bubbles:true}));
const px=s=>{ const c2=cv.getContext('2d'), dpr=cv.width/cv.getBoundingClientRect().width, p=P(s.la,s.lo);
  const d=c2.getImageData(Math.round(p[0]*dpr),Math.round(p[1]*dpr),1,1).data; return [d[0],d[1],d[2]]; };
const zones=()=>[{kind:'zone',zone:'occupied',pts:BASE.regions['Крим'][0].map(p=>[p[0],p[1]])},
                 {kind:'zone',zone:'ukraine',pts:BASE.countries.UKR[0].filter((p,i)=>i%6===0).map(p=>[p[0],p[1]])}];
(async()=>{ try{
  S.ghosts=[]; S.objs=zones(); S.tfilter={on:false,from:'20:00',to:'06:00'};
  const sel=document.getElementById('sightSpan'); sel.value=[...sel.options].map(o=>o.value).filter(v=>/^\d{4}-\d\d$/.test(v))[1]; sel.onchange();
  for(let i=0;i<60&&!S.sightSpan;i++) await sleep(500);
  ok('0 зведення завантажилось', !!S.sightSpan&&S.sight.length>500, S.sight.length);
  zoomTo(BASE.regions['Крим'].map(pts=>({pts}))); S.sightSel=[]; S.sightHover=null; endPass(); draw();
  const N0=S.sight.length, M0=STAT.msgs;

  // A. мітки над зонами
  const inZ=S.sight.filter(s=>{ if(s.area||s.aim||s.n<=3) return false; const p=P(s.la,s.lo), h=hit(p[0],p[1]); return h&&h.o.kind==='zone'; }).slice(0,80);
  const a=inZ.map(px), keep=S.objs; S.objs=[]; endPass(); draw(); const b=inZ.map(px); S.objs=keep; endPass(); draw();
  const diff=a.map((v,i)=>Math.max(Math.abs(v[0]-b[i][0]),Math.abs(v[1]-b[i][1]),Math.abs(v[2]-b[i][2]))).sort((x,y)=>x-y);
  ok('A1 зона не тонує мітки (різниця кольору з зоною і без неї)', inZ.length>=40&&diff[diff.length>>1]<=3&&diff[diff.length-1]<=12, {n:inZ.length,median:diff[diff.length>>1],max:diff[diff.length-1]});
  // порядок обʼєктів між собою не міняється: зображення під своєю зоною лишається під нею
  S.objs=[{kind:'image',tag:'img-під'},{kind:'zone',zone:'своя-не-підкладка',tag:'зона-своя',pts:[[45,34],[45.2,34],[45.2,34.3]]},
          ...zones(),{kind:'image',tag:'img-над'},{kind:'arrow',tag:'стрілка',pts:[[45,34],[45.2,34.3]]}];
  endPass(); const list=drawList().map(o=>o.tag||o.kind), cut=zoneCut(drawList());
  S.objs=keep; endPass(); draw();
  ok('A2 межа — одразу за останньою зоною; зображення під нею лишається під нею', JSON.stringify(list)===JSON.stringify(['zone','zone','img-під','зона-своя','img-над','стрілка'])&&cut===4, {list,cut});
  ok('A3 без зон мітки лягають під усе намальоване', zoneCut([{kind:'route'},{kind:'impact'}])===0&&zoneCut([])===0, 0);

  // B. вибір і панорама
  const s0=inZ[0], p0=P(s0.la,s0.lo);
  click(p0[0],p0[1]);
  ok('B1 клік по мітці в зоні вибирає мітку, не зону', S.sightSel.length===1&&S.sightSel[0]===s0&&!S.sel&&!document.getElementById('del').disabled, {sel:S.sightSel.length,obj:!!S.sel});
  S.sightSel=[]; const v0=[S.view.x,S.view.y];
  ev('pointerdown',p0[0],p0[1]); ev('pointermove',p0[0]+120,p0[1]+60); ev('pointerup',p0[0]+120,p0[1]+60);
  ok('B2 тягнути від мітки — панорама, а не вибір', S.sightSel.length===0&&Math.abs(S.view.x-v0[0])*S.view.k>50, {sel:S.sightSel.length,dx:(S.view.x-v0[0])*S.view.k});
  S.view.x=v0[0]; S.view.y=v0[1]; draw();
  const s1=inZ[1], p1=P(s1.la,s1.lo);
  click(p0[0],p0[1]); click(p1[0],p1[1],{shiftKey:true});
  ok('B3 Shift+клік додає', S.sightSel.length===2, S.sightSel.length);
  click(p1[0],p1[1],{shiftKey:true});
  ok('B4 Shift+клік по вибраній знімає', S.sightSel.length===1&&S.sightSel[0]===s0, S.sightSel.length);
  key('Escape'); ok('B5 Esc знімає вибір', S.sightSel.length===0, S.sightSel.length);
  const mark={kind:'impact',cat:'impact',la:s0.la,lo:s0.lo,size:10,label:'тест'}; S.objs.push(mark); endPass(); draw();
  click(p0[0],p0[1]);
  ok('B6 обʼєкт над міткою забирає клік собі', S.sel===mark&&S.sightSel.length===0, {obj:S.sel===mark,s:S.sightSel.length});
  S.objs=S.objs.filter(o=>o!==mark); S.sel=null; endPass(); draw();
  // своя (не підкладка) зона над міткою: мітка намальована вище, тож клік — їй
  const zid=(ZONES.find(z=>!ZONE_DEF[z.id]||!ZONE_DEF[z.id].base)||{}).id||'test-zone';
  const own={kind:'zone',zone:zid,pts:[[s0.la-.3,s0.lo-.4],[s0.la+.3,s0.lo-.4],[s0.la+.3,s0.lo+.4],[s0.la-.3,s0.lo+.4]]};
  S.objs.push(own); endPass(); draw(); S.sightSel=[];
  const under=hit(p0[0],p0[1],true);
  click(p0[0],p0[1]);
  ok('B8 своя зона під міткою кліку не забирає', !!under&&under.o===own&&S.sightSel.length===1&&S.sel!==own, {zoneHit:!!under&&under.o===own,sel:S.sightSel.length,obj:S.sel===own});
  S.objs=S.objs.filter(o=>o!==own); S.sel=null; S.sightSel=[]; endPass(); draw();
  click(p0[0],p0[1]); click(1250,950);
  ok('B7 клік повз мітки знімає вибір', S.sightSel.length===0, S.sightSel.length);

  // C. видалення
  click(p0[0],p0[1]); key('Delete');
  ok('C1 Delete прибирає мітку, статистика меншає на її число', N0-S.sight.length===1&&M0-STAT.msgs===s0.n&&S.sightSpan.gone.size===1&&!S.sight.includes(s0), {d:N0-S.sight.length,m:M0-STAT.msgs,n:s0.n});
  document.getElementById('undo').click();
  ok('C2 Ctrl+Z повертає', S.sight.length===N0&&STAT.msgs===M0&&S.sightSpan.gone.size===0, S.sight.length);
  document.getElementById('redo').click();
  ok('C3 повтор прибирає знову', N0-S.sight.length===1, S.sight.length);
  document.getElementById('undo').click();
  const arrow={kind:'arrow',pts:[[45.0,34.0],[45.3,34.4]]}; S.objs.push(arrow); endPass(); draw();
  ev('pointerdown',300,880,{shiftKey:true}); ev('pointermove',900,300,{shiftKey:true}); ev('pointerup',900,300,{shiftKey:true});
  const picked=[S.sel,...S.selMore].filter(Boolean), nSel=S.sightSel.length;
  ok('C4 рамка бере мітки й стрілку, але не зони підкладки', nSel>20&&picked.length===1&&picked[0]===arrow, {nSel,picked:picked.map(o=>o.kind)});
  key('Delete');
  ok('C5 Delete після рамки: мітки й стрілка геть, зони цілі', N0-S.sight.length===nSel&&!S.objs.includes(arrow)&&S.objs.filter(isBaseZone).length===2, {d:N0-S.sight.length,z:S.objs.filter(isBaseZone).length});
  document.getElementById('undo').click();
  ok('C6 один крок назад повертає все', S.sight.length===N0&&S.objs.some(o=>o.kind==='arrow'), S.sight.length);
  S.objs=S.objs.filter(o=>o.kind!=='arrow'); endPass();

  // D. область цілком — і з вікном годин теж уся
  S.tfilter={on:true,from:'02:00',to:'04:00'}; refresh();
  const box=()=>document.getElementById('sightStats');
  const allUa=S.sight.filter(s=>s.reg==='~ua').length, visUa=(STAT.rows.find(r=>r.key==='~ua')||{places:[]}).places.length;
  if(box().querySelector('[data-sa]')) box().querySelector('[data-sa]').click();
  box().querySelector('[data-sr="~ua"]').click(); box().querySelector('[data-sx="~ua"]').click();
  S.tfilter.on=false; refresh();
  ok('D1 «прибрати її мітки» прибирає всю область, а не лише видиме у вікні годин', allUa>visUa&&S.sight.filter(s=>s.reg==='~ua').length===0&&N0-S.sight.length===allUa, {allUa,visUa,left:S.sight.filter(s=>s.reg==='~ua').length});
  ok('D2 рядка області в статистиці нема, є «повернути прибрані»', !STAT.rows.some(r=>r.key==='~ua')&&!!box().querySelector('[data-su]'), 0);
  box().querySelector('[data-su]').click();
  ok('D3 «повернути прибрані» повертає', S.sight.length===N0&&STAT.msgs===M0&&!box().querySelector('[data-su]'), S.sight.length);

  // E. експорт: зони раніше за мітки, прибраного нема
  const exportSvg=async()=>{ let svg=null; const orig=URL.createObjectURL.bind(URL);
    URL.createObjectURL=bl=>{ if(/svg/.test(bl.type)) bl.text().then(t=>{ svg=t; }); return orig(bl); };
    document.getElementById('exportSvg').click();
    for(let i=0;i<80&&!svg;i++) await sleep(500);
    URL.createObjectURL=orig; return svg||''; };
  const zc=hexToRgb(ZONES.find(z=>z.id==='occupied').col), yc=hexToRgb(sightCol());
  const count=(t,re)=>[...t.matchAll(new RegExp(re,'g'))].map(m=>m.index);
  const svg0=await exportSvg(), zi=count(svg0,zc), y0=count(svg0,yc);
  ok('E1 у SVG заливка й штрих зони йдуть до першої мітки', zi.length>10&&y0.length>500&&zi.filter(i=>i<y0[0]).length>=zi.length-2, {zones:zi.length,dots:y0.length,before:zi.filter(i=>i<y0[0]).length});
  click(p0[0],p0[1]); key('Delete');
  const y1=count(await exportSvg(),yc);
  ok('E2 прибрана мітка зникає з експорту — рівно одна', y0.length-y1.length===1, {before:y0.length,after:y1.length});
  document.getElementById('undo').click();
}catch(e){ R.push('EXC '+(e.stack||e)); }
  window.__res=R;
})();
function hexToRgb(h){ const n=parseInt(h.slice(1),16); return (n>>16)+',\\s*'+((n>>8)&255)+',\\s*'+(n&255); }
return 'started'; })()
