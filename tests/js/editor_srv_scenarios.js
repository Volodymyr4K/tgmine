// Автозбереження карт на сервер — сценарії в живому редакторі проти
// підробленого /api/maps (те саме правило, що у functions/api/_store.js).
// Кожен сценарій — із затирань, знайдених в історії mapper/maps 1.10.2026.
// У pytest не входить: потрібен браузер. Запуск (gstack browse):
//   browse goto http://127.0.0.1:<порт>/editor.html?v=$(date +%s)   # зачекати ~8 с
//   browse eval tests/js/editor_srv_scenarios.js                    # зачекати ~6 с
//   browse eval <файл із `(()=>JSON.stringify(window.__res,null,1))()`>
// Усі рядки мають починатись з «ok». Сценарій чистить localStorage['tgmine-srv']
// і міняє обʼєкти на екрані — на робочій карті не запускати.
(()=>{
const R=[], ok=(name,cond,extra)=>R.push((cond?'ok   ':'FAIL ')+name+(cond?'':' :: '+JSON.stringify(extra)));
const files={}; let shaN=0, user='editor', puts=[], hang=false, confirms=[], confirmAns=true;
const _fetch=window.fetch;
window.confirm=m=>{ confirms.push(m); return confirmAns; };
window.fetch=(u,o)=>{
  u=String(u);
  if(!u.startsWith('/api/maps')) return _fetch(u,o);
  const J=(b,st=200)=>Promise.resolve(new Response(JSON.stringify(b),{status:st}));
  if(u==='/api/maps') return J({maps:Object.keys(files).map(id=>({id}))});
  const id=u.split('/').pop().split('?')[0], cur=files[id];
  if(!o||!o.method||o.method==='GET') return cur?J({sha:cur.sha,map:cur.map}):J({error:'нема'},404);
  if(o.method==='DELETE'){ delete files[id]; return J({deleted:true}); }
  const b=JSON.parse(o.body);
  puts.push({id,sha:b.sha||'',loose:Array.isArray(b.loose)&&b.loose.length>0,force:!!b.force,objs:b.map.objs.length});
  if(hang) return new Promise(()=>{});
  const write=()=>{ files[id]={sha:'s'+(++shaN),map:b.map,by:user}; return J({id,sha:files[id].sha}); };
  if(!cur) return write();
  if(b.sha===cur.sha||b.force) return write();
  if(b.sha&&Array.isArray(b.loose)&&b.loose.includes(srvHash(JSON.stringify(cur.map)))) return write();
  return J({error:'на сервері вже є інша версія',conflict:true,id,sha:cur.sha,by:cur.by,objs:cur.map.objs.length,sub:cur.map.sub},409);
};
const z=ZONES_DEFAULT.find(z=>z.base);
const zone=()=>({kind:'zone',zone:z.id,pts:[[50,30],[51,31],[50,32]]});
const routes=n=>Array.from({length:n},(_,i)=>({kind:'route',pts:[[50,36+i*0.01],[52,38]],type:TYPES[0].id}));
const hints=(n,night)=>routes(n).map(o=>Object.assign(o,{origin:'night:'+(night||'2026-10-01')}));
const setMap=(n,sub)=>{ S.objs=[zone(),...routes(n)]; S.sub=sub; S.title='Нічний наліт'; };
const fresh=()=>{ localStorage.removeItem('tgmine-srv'); puts=[]; confirms=[]; confirmAns=true; hang=false;
  Object.assign(SRV,{on:true,id:'',sha:'',at:0,n:0,h:0,loose:[],block:null,told:'',wait:'',busy:false,pend:false,err:''}); clearTimeout(SRV.t); };
const reload=()=>{ Object.assign(SRV,{id:'',sha:'',at:0,n:0,h:0,loose:[],block:null,wait:'',busy:false}); srvAdopt(srvId()); };
const srvObjs=id=>files[id]?files[id].map.objs.length:null;
const seed=(id,n,by,sub)=>{ files[id]={sha:'s'+(++shaN),map:{title:'Нічний наліт',sub,objs:[zone(),...routes(n)]},by}; };
const hud=()=>document.getElementById('saved').textContent;
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
const A='2026-10-02-nichnyi-nalit', B='2026-10-01-nichnyi-nalit', C='2026-09-26-nichnyi-nalit';

(async()=>{ try{
  // A. створення і продовження
  fresh(); user='editor'; setMap(12,'ніч на 2 жовтня 2026');
  await srvPush(false);
  ok('A1 нова карта створюється', srvObjs(A)===13&&SRV.sha===files[A].sha&&puts.length===1&&puts[0].sha==='', puts);
  ok('A2 власність записана в браузері', JSON.parse(localStorage.getItem('tgmine-srv')).id===A);
  S.objs.push(...routes(1)); puts=[]; await srvPush(false);
  ok('A3 свій файл: пише зі своїм sha', srvObjs(A)===14&&puts[0].sha!==''&&!SRV.block, puts);
  ok('A4 рядок під кнопками', /на сервері: 2026-10-02/.test(document.getElementById('srvHint').textContent), document.getElementById('srvHint').textContent);

  // C. чужий наявний файл (26 вересня: завислий підзаголовок власника)
  fresh(); user='volodymyr'; seed(C,57,'editor','ніч на 26 вересня 2026'); const shaC=files[C].sha;
  setMap(16,'ніч на 26 вересня 2026');
  await srvPush(false);
  ok('C1 чужу карту не затерто', srvObjs(C)===58&&files[C].sha===shaC, srvObjs(C));
  ok('C2 стоїть із причиною', SRV.block&&SRV.block.why==='exists'&&SRV.block.info.by==='editor', SRV.block);
  ok('C3 видно в HUD і в рядку', /на сервер не йде/.test((savedTick(),hud()))&&/вже є карта/.test(document.getElementById('srvHint').textContent), hud());
  puts=[]; S.objs.push(...routes(3)); await srvPush(false); await srvPush(false);
  ok('C4 далі сама не стукає', puts.length===0, puts);
  srvFlush(); ok('C5 і на закритті вкладки', puts.length===0, puts);
  confirmAns=false; await srvPush(true);
  ok('C6 кнопка питає; «ні» — нічого не міняє', confirms.length===1&&/57|58/.test(confirms[0])&&/editor/.test(confirms[0])&&srvObjs(C)===58&&puts.length===1&&!puts[0].force, {confirms,puts});
  confirmAns=true; puts=[]; confirms=[]; await srvPush(true);
  ok('C7 кнопка, «так» — замінює і стає своїм', confirms.length===1&&srvObjs(C)===20&&puts.length===2&&puts[1].force&&SRV.sha===files[C].sha&&!SRV.block, {confirms,puts,n:srvObjs(C)});
  S.objs.push(...routes(1)); puts=[]; await srvPush(false);
  ok('C8 після свідомої заміни пише сама', srvObjs(C)===21&&puts.length===1, puts);

  // D. перезавантаження посеред роботи
  fresh(); user='editor'; delete files[A]; setMap(30,'ніч на 2 жовтня 2026'); await srvPush(false);
  reload();
  S.objs.push(...routes(2)); puts=[]; await srvPush(false);
  ok('D1 після перезавантаження свій файл лишається своїм', srvObjs(A)===33&&puts[0].sha!==''&&!SRV.block, puts);

  // E. наступного ранку (17,18,19,25,28 вересня): власність застаріла
  SRV.at=Date.now()-4*3600e3; srvOwnSave(); reload();
  S.objs=[zone(),...routes(11)]; puts=[]; await srvPush(false);
  ok('E1 давню свою карту сама не чіпає', srvObjs(A)===33&&puts.length===1&&puts[0].sha===''&&SRV.block&&SRV.block.why==='exists', {puts,b:SRV.block,n:srvObjs(A)});

  // F. обвал: стер більшість обʼєктів у тому ж сеансі (23.09 11:55, 25.09 10:23)
  fresh(); delete files[A]; setMap(50,'ніч на 2 жовтня 2026'); await srvPush(false);
  S.objs=[zone(),...routes(11)]; puts=[]; await srvPush(false);
  ok('F1 обвал не йде на сервер', srvObjs(A)===51&&puts.length===0&&SRV.block&&SRV.block.why==='collapse', {puts,b:SRV.block});
  S.objs=[zone(),...routes(40)]; await srvPush(false);
  ok('F2 обʼєкти повернулись (undo) — пише далі', srvObjs(A)===41&&!SRV.block, {b:SRV.block,n:srvObjs(A)});
  S.objs=[zone(),...routes(30)]; await srvPush(false);
  ok('F3 звичайне проріджування (75%) проходить', srvObjs(A)===31&&!SRV.block, srvObjs(A));
  S.objs=[zone(),...routes(5)]; await srvPush(false); puts=[]; confirms=[]; await srvPush(true);
  ok('F4 обвал + кнопка = свідомо, без запитання', srvObjs(A)===6&&confirms.length===0&&!SRV.block, {n:srvObjs(A),confirms});
  S.objs=[zone()]; puts=[]; await srvPush(false); srvFlush();
  ok('F5 сама підкладка не йде взагалі', puts.length===0&&srvObjs(A)===6, puts);

  // обвал за загальним ліком, коли намальованого руками мало (правило «руками» мовчить)
  fresh(); delete files[A]; S.objs=[zone(),...hints(50),...routes(2)]; S.sub='ніч на 2 жовтня 2026'; await srvPush(false);
  S.objs=[zone(),...hints(5),...routes(2)]; puts=[]; await srvPush(false);
  ok('F6 обвал за загальним ліком', srvObjs(A)===53&&puts.length===0&&SRV.block&&SRV.block.why==='collapse', {n:srvObjs(A),b:SRV.block});
  // мала карта (жодне правило обвалу не діє) -> сама підкладка
  fresh(); delete files[A]; setMap(3,'ніч на 2 жовтня 2026'); await srvPush(false);
  S.objs=[zone()]; puts=[]; await srvPush(false); srvFlush();
  ok('F7 малу карту сама підкладка не затирає', srvObjs(A)===4&&puts.length===0, {n:srvObjs(A),puts});

  // G. чистий аркуш: «Нова карта», «Прибрати все з ночі», інша ніч
  for(const [name,act] of [['Нова карта',()=>document.getElementById('clear').click()],
                           ['Прибрати все з ночі',()=>document.getElementById('nightWipe').click()],
                           ['інша ніч',()=>{ const s=document.getElementById('nightSel'); s.value=s.options[1].value; s.onchange(); }]]){
    fresh(); delete files[B]; setMap(40,'ніч на 1 жовтня 2026'); await srvPush(false);
    const sha0=files[B].sha; act();
    const disowned=!SRV.sha&&!localStorage.getItem('tgmine-srv');
    S.objs=S.objs.filter(isBaseZone).concat(routes(45)); S.sub='ніч на 1 жовтня 2026'; puts=[]; await srvPush(false);
    ok('G '+name+': файл більше не свій, готова карта ціла', disowned&&srvObjs(B)===41&&files[B].sha===sha0&&SRV.block&&SRV.block.why==='exists', {disowned,n:srvObjs(B),b:SRV.block,puts});
    S.sub='ніч на 2 жовтня 2026'; delete files[A]; await srvPush(false);
    ok('G '+name+': нова ніч створюється під своєю назвою', srvObjs(A)===S.objs.length&&srvObjs(B)===41&&!srvBlocked(), {a:srvObjs(A),b:srvObjs(B)});
  }

  // H. запис на закритті вкладки
  fresh(); delete files[A]; setMap(20,'ніч на 2 жовтня 2026'); await srvPush(false);
  S.objs.push(...routes(1)); puts=[]; srvFlush();
  const st1=JSON.parse(localStorage.getItem('tgmine-srv'));
  ok('H1 перед відправкою записано відбиток посланого', Array.isArray(st1.loose)&&st1.loose.length===1&&st1.loose[0]===srvHash(JSON.stringify(mapPayload()))&&puts.length===1&&puts[0].sha!==''&&!puts[0].loose, {st1,puts});
  await sleep(50);
  ok('H2 вкладку лише сховали: відповідь прийшла, sha точний', SRV.sha===files[A].sha&&SRV.loose.length===0&&srvObjs(A)===22&&!SRV.busy, {sha:SRV.sha,f:files[A].sha});
  // сторінку закрили: запис дійшов, відповіді нема
  const shaOld=SRV.sha; S.objs.push(...routes(1)); hang=true; srvFlush(); hang=false;
  files[A]={sha:'s'+(++shaN),map:JSON.parse(JSON.stringify(mapPayload())),by:'editor'};      // сервер записав
  reload();
  ok('H3 після перезавантаження sha старий, відбиток є', SRV.sha===shaOld&&SRV.loose.length===1, {sha:SRV.sha,loose:SRV.loose});
  S.objs.push(...routes(1)); puts=[]; await srvPush(false);
  ok('H4 свій запис на закритті не блокує', srvObjs(A)===24&&puts[0].loose&&!SRV.block&&SRV.loose.length===0, {puts,b:SRV.block});
  // те саме, але між тим файл замінив інший користувач
  S.objs.push(...routes(1)); hang=true; srvFlush(); hang=false;
  seed(A,60,'volodymyr','ніч на 2 жовтня 2026');
  reload();
  puts=[]; await srvPush(false);
  ok('H5 у файлі вже не мій запис — відбиток не відкриває', srvObjs(A)===61&&puts[0].loose&&SRV.block&&SRV.block.why==='changed'&&SRV.block.info.by==='volodymyr', {n:srvObjs(A),b:SRV.block});
  // той самий логін у другому браузері замінив файл — теж ні
  fresh(); delete files[A]; setMap(20,'ніч на 2 жовтня 2026'); await srvPush(false);
  S.objs.push(...routes(1)); hang=true; srvFlush(); hang=false; seed(A,70,'editor','ніч на 2 жовтня 2026'); reload();
  puts=[]; await srvPush(false);
  ok('H6 той самий логін з іншого браузера — теж не перекриває', srvObjs(A)===71&&SRV.block&&SRV.block.why==='changed', {n:srvObjs(A),b:SRV.block});
  // у файлі текст тієї самої довжини, але інший — відбиток має це бачити
  fresh(); delete files[A]; setMap(20,'ніч на 2 жовтня 2026'); await srvPush(false);
  S.objs.push(...routes(1)); hang=true; srvFlush(); hang=false;
  { const m=JSON.parse(JSON.stringify(mapPayload())); m.title='Нічний налім'; files[A]={sha:'s'+(++shaN),map:m,by:'editor'}; }
  reload(); S.objs.push(...routes(1)); puts=[]; await srvPush(false);
  ok('H8 та сама довжина, інший вміст — не свій запис', files[A].map.title==='Нічний налім'&&SRV.block&&SRV.block.why==='changed', {t:files[A].map.title,b:SRV.block});
  // два записи на закритті поспіль: на сервері може лежати будь-який із них
  fresh(); delete files[A]; setMap(20,'ніч на 2 жовтня 2026'); await srvPush(false);
  S.objs.push(...routes(1)); hang=true; srvFlush(); SRV.busy=false; const first=mapPayload();
  S.objs.push(...routes(1)); srvFlush(); hang=false;
  files[A]={sha:'s'+(++shaN),map:JSON.parse(JSON.stringify(first)),by:'editor'}; reload();
  S.objs.push(...routes(1)); puts=[]; await srvPush(false);
  ok('H7 дійшов лише перший із двох записів на закритті — теж свій', srvObjs(A)===24&&!SRV.block, {n:srvObjs(A),b:SRV.block,puts});
  // I. не свій файл на закритті не створюється
  fresh(); delete files[A]; setMap(20,'ніч на 2 жовтня 2026'); srvFlush();
  ok('I1 чужий/новий файл на закритті не пишеться', puts.length===0&&!files[A], puts);

  // M. файл створюється, коли на карті є робота, а не самі взяті підказки
  // (21, 23, 25 вересня: власник зранку першим створював файл ночі)
  fresh(); user='volodymyr'; delete files[A]; S.objs=[zone(),...hints(53)]; S.sub='ніч на 2 жовтня 2026';
  await srvPush(false); srvFlush();
  ok('M1 самі підказки файла не створюють', puts.length===0&&!files[A]&&!srvBlocked(), puts);
  ok('M2 і це сказано словами, без тривоги', /намальоване руками/.test(document.getElementById('srvHint').textContent)&&!/не йде/.test((savedTick(),hud())), document.getElementById('srvHint').textContent);
  fresh(); user='editor'; S.objs=[zone(),...hints(49)]; await srvPush(false);
  S.objs.push(...routes(1)); await srvPush(false);
  ok('M3 перший свій обʼєкт — файл створено', srvObjs(A)===51&&puts.length===1&&SRV.sha===files[A].sha, puts);
  S.objs=[zone(),...hints(45)]; puts=[]; await srvPush(false);
  ok('M4 свій файл далі пишеться і без намальованого руками', srvObjs(A)===46&&puts.length===1, {n:srvObjs(A),puts});
  fresh(); delete files[A]; S.objs=[zone(),...hints(30)]; await srvPush(false,false,true);
  ok('M5 експорт PNG кладе й карту з самих підказок', srvObjs(A)===31, srvObjs(A));
  fresh(); delete files[A]; S.objs=[zone(),...hints(30)]; await srvPush(true);
  ok('M6 кнопка кладе завжди', srvObjs(A)===31&&confirms.length===0, srvObjs(A));
  // 23 вересня 11:56: готову карту затерли 83 щойно взяті підказки
  fresh(); delete files[A]; S.objs=[zone(),...hints(17),...routes(24)]; await srvPush(false);
  S.objs=[zone(),...hints(83)]; puts=[]; await srvPush(false);
  ok('M7 обвал «руками» при більшому загальному ліку', srvObjs(A)===42&&puts.length===0&&SRV.block&&SRV.block.why==='collapse', {n:srvObjs(A),b:SRV.block});
  // застарілий підзаголовок: попередження в запитанні
  fresh(); seed(B,58,'editor','ніч на 1 жовтня 2026'); const N0=window.NIGHT; window.NIGHT={date:'2026-10-01'};
  S.objs=[zone(),...hints(20,'2026-10-01'),...routes(2)]; S.sub='ніч на 1 жовтня 2026'; confirmAns=false; await srvPush(true);
  ok('M8 кнопка попереджає про старий підзаголовок', confirms.length===1&&/УВАГА/.test(confirms[0])&&/02\.10/.test(confirms[0])&&srvObjs(B)===59, confirms);
  S.sub='ніч на 2 жовтня 2026'; delete files[A]; confirms=[]; await srvPush(true);
  ok('M9 з правильним підзаголовком — без попередження і без запитання', confirms.length===0&&srvObjs(A)===23, {confirms,n:srvObjs(A)});
  window.NIGHT=N0;

  // K. відкрив із сервера — файл свій
  fresh(); user='volodymyr'; seed(B,58,'editor','ніч на 1 жовтня 2026');
  await srvRenderList(true); document.getElementById('srvSel').value=B; await document.getElementById('srvOpen').onclick();
  S.objs.push(...routes(1)); puts=[]; await srvPush(false);
  ok('K1 відкрив із сервера — далі пише сама', srvObjs(B)===60&&puts[0].sha!==''&&!SRV.block, {n:srvObjs(B),puts});
  // L. прибрав із сервера — власність знято
  document.getElementById('srvSel').value=B; await document.getElementById('srvDel').onclick();
  ok('L1 прибрав із сервера — власність знято', !SRV.sha&&!files[B], SRV.sha);
}catch(e){ R.push('EXC '+(e.stack||e)); }
  window.__res=R;
})();
return 'started'; })()
