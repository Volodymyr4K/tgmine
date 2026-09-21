#!/usr/bin/env python3
"""Карта нальоту. Три шари з різною семантикою — і це головне рішення.

Попередня версія показувала все однаково: точки з'являлись і зникали, треки
малювались цілими відрізками одразу. Виходило нечитабельно, бо різні за суттю
речі виглядали однаково.

Тепер розділено:
  1. МІСЦЯ (постійні). Населений пункт, де хоч раз щось зафіксували, лишається
     на карті назавжди й темніє. Спостереження не «зникає» — накопичена історія
     нальоту завжди видима.
  2. ІМПУЛЬСИ (миттєві). Нове повідомлення = кільце, що розходиться й гасне.
     Це подія спостереження, вона справді миттєва — і виглядає миттєвою.
  3. КОМЕТИ (рухомі). Трек — це не відрізок, а об'єкт, що ЛЕТИТЬ уздовж шляху
     в реальному часі, з хвостом. Тільки так рух читається як рух.

Плюс смуга часу знизу: видно, де ти в нальоті й де піки.

Запуск:  python3 makeraid.py raid_2026-07-17.json
"""
import json
import re
import sys
from pathlib import Path

TPL = r"""<!doctype html>
<html lang="uk"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>__TITLE__</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"
      integrity="sha384-sHL9NAb7lN7rfvG5lfHpm643Xkcjzp4jFvuavGOndn6pjVqS6ny56CAt3nsEVT4H"
      crossorigin="anonymous">
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"
        integrity="sha384-cxOPjt7s7Iz04uaHJceBmS+qpjv2JkIHNVcuOrM+YHwZOmJGBXI00mdUXEq65HTH"
        crossorigin="anonymous"></script>
<style>
  :root{--bg:#060910;--panel:#0c1119;--line:#18212c;--fg:#e6eef7;--dim:#68798c;
        --cyan:#38d4dd;--red:#ff4d63;--amber:#ffb01f;--violet:#a78bfa;--green:#4ade80}
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--fg);height:100vh;overflow:hidden;
       font:13px/1.5 ui-monospace,SFMono-Regular,Menlo,monospace;
       display:grid;grid-template-columns:1fr 360px}
  @media(max-width:960px){body{grid-template-columns:1fr;grid-template-rows:1fr 40vh}}
  #wrap{position:relative}
  #map{position:absolute;inset:0} .leaflet-container{background:#060910}
  canvas.fx{position:absolute;top:0;left:0;width:100%;height:100%;
           pointer-events:none;z-index:450}
  .leaflet-control-attribution{background:rgba(6,9,16,.75)!important;color:#3f4d5c!important;font-size:9px}
  .leaflet-control-attribution a{color:#4d6478!important}

  /* верхня плашка з фазою — щоб було зрозуміло ЩО відбувається */
  /* На карті лишається мінімум: годинник і що відбувається. Решта цифр
     переїхала в панель — на мапі вони лежали просто поверх території
     і заважали читати саму подію. */
  /* Кнопки масштабу Leaflet за замовчуванням сідають у ЛІВИЙ ВЕРХНІЙ кут —
     рівно туди, де банер із годинником і кнопка «Зведення» з шапки. Три шари
     налазили один на одного, і години читались як «:2:10». Опускаємо кнопки
     над смугу часу; смуга 66px, тому 74px лишає зазор. */
  .leaflet-top.leaflet-left{top:auto;bottom:74px}
  /* 44px, а не 36: шапка з падінгом і кнопками займає ~40px, банер лізав під неї. */
  #banner{position:absolute;top:44px;left:12px;z-index:500;padding:9px 13px;
          pointer-events:none;border-radius:8px;background:rgba(6,9,16,.72);
          border:1px solid rgba(40,58,76,.6);backdrop-filter:blur(6px)}
  #clock{font-size:26px;color:var(--cyan);letter-spacing:.03em;font-variant-numeric:tabular-nums}
  #phase{font-size:11.5px;color:var(--amber);margin-top:1px;max-width:330px}
  #front{font-size:10px;color:var(--dim);margin:10px 0 6px;line-height:1.6}
  #ledger{font-size:11px;margin-bottom:10px;letter-spacing:.02em;
          padding-bottom:10px;border-bottom:1px solid var(--line)}
  #ledger b{font-variant-numeric:tabular-nums}
  #explain{font-size:10px;color:#5d6f82;margin-top:6px;max-width:560px;line-height:1.5}

  /* смуга часу */
  #strip{position:absolute;left:0;right:0;bottom:0;height:66px;z-index:500;
         background:linear-gradient(0deg,rgba(6,9,16,.94),rgba(6,9,16,.2));padding:6px 14px 8px}
  #strip svg{width:100%;height:38px;display:block}
  #ctrl{display:flex;gap:6px;align-items:center;justify-content:center;margin-top:2px}
  button{background:#131c26;color:var(--fg);border:1px solid var(--line);border-radius:5px;
         padding:4px 10px;cursor:pointer;font:inherit;font-size:11px}
  button:hover{border-color:#2b3c4d} button.on{background:var(--cyan);color:#04222a;border-color:var(--cyan)}

  aside{background:var(--panel);border-left:1px solid var(--line);overflow-y:auto;padding:15px}
  h1{font-size:12.5px;letter-spacing:.13em;margin:0 0 4px;text-transform:uppercase}
  .sub{color:var(--dim);font-size:10px;margin-bottom:13px;line-height:1.6}
  .counters{display:grid;grid-template-columns:repeat(4,1fr);gap:5px;margin-bottom:12px}
  .c{background:#090e15;border:1px solid var(--line);border-radius:5px;padding:7px 2px;text-align:center}
  .c b{display:block;font-size:17px;font-variant-numeric:tabular-nums}
  .c span{font-size:8px;color:var(--dim);letter-spacing:.05em}
  .hdr{font-size:9px;letter-spacing:.15em;color:var(--dim);margin:13px 0 7px;text-transform:uppercase;
       border-top:1px solid var(--line);padding-top:10px}
  .trk{padding:5px 8px;margin-bottom:4px;border-radius:4px;font-size:10px;background:#090e15;
       border-left:2px solid #23303e;cursor:pointer;display:flex;justify-content:space-between;gap:6px}
  .trk.live{border-left-color:var(--violet);background:#12101f}
  .trk.done{opacity:.4}
  .trk:hover{background:#111a24} .trk b{font-weight:500} .trk span{color:var(--dim);white-space:nowrap}
  .ev{border-left:2px solid var(--line);padding:3px 0 3px 8px;margin-bottom:5px;font-size:10px}
  .ev.pvo{border-color:var(--red)} .ev.fix{border-color:var(--cyan)} .ev.warn{border-color:var(--amber)}
  .ev.off{border-color:var(--green)}
  .ev time{color:var(--cyan);margin-right:5px} .ev a{color:#3f5364;text-decoration:none;font-size:9px}
  .km{float:right;color:var(--dim);font-size:9px}
  .legend{font-size:9.5px;color:var(--dim);margin-top:12px;border-top:1px solid var(--line);
          padding-top:10px;line-height:2}
  .legend i{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:6px;vertical-align:middle}
  /* Панель обʼєктів: прихована за кнопкою, вмикається по категоріях.
     Не «все й одразу», а вибір — інакше тисячі значків знову дадуть кашу. */
  #layers{position:absolute;top:36px;right:12px;z-index:600;text-align:right}
  #layToggle{pointer-events:auto;background:rgba(20,30,42,.95);color:#e6eef7;
    border:1px solid #38566e;border-radius:6px;padding:7px 13px;cursor:pointer;
    font:inherit;font-size:11.5px;box-shadow:0 3px 12px rgba(0,0,0,.5)}
  #layToggle:hover{border-color:#31465c}
  #layPanel{margin-top:6px;background:rgba(9,14,20,.96);border:1px solid #22303e;
    border-radius:8px;padding:9px 11px;text-align:left;max-width:230px;
    box-shadow:0 10px 30px rgba(0,0,0,.6)}
  #layPanel label{display:flex;align-items:center;gap:7px;font-size:11px;
    color:#b6c4d2;padding:3px 0;cursor:pointer}
  #layPanel input{accent-color:#38d4dd}
  #layPanel .dot{width:9px;height:9px;border-radius:2px;flex:0 0 auto}
  #layPanel .cnt{margin-left:auto;color:#5d6f82;font-size:10px}
  #layPanel .hint{font-size:9px;color:#5d6f82;margin:2px 0 4px;line-height:1.5}
  .warnbox{margin-top:11px;padding:8px 10px;border:1px solid #3a2a15;background:#140f06;
           border-radius:5px;font-size:9px;color:#c39552;line-height:1.65}
  .note{font-size:8.5px;color:#46586a;margin-top:9px;line-height:1.75}
  /* Шапка поверх карти: без неї програвач був глухим кутом — з нього
     не було виходу на звіт чи зведення */
  #nav{position:absolute;top:0;left:0;right:0;z-index:600;display:flex;gap:4px;
       align-items:center;padding:8px 12px;pointer-events:none;
       background:linear-gradient(180deg,rgba(6,9,16,.95),rgba(6,9,16,.5) 70%,rgba(6,9,16,0))}
  #nav a{pointer-events:auto;color:#8ea0b2;font-size:11px;padding:4px 9px;
         border-radius:5px;border:1px solid #1d2733;background:rgba(12,17,25,.9);
         text-decoration:none}
  #nav a:hover{color:#e6eef7;border-color:#31465c}
  #nav .t{color:#5d6f82;font-size:10px;margin-left:auto}
  /* Попап мусить бути ГЛУХИМ. Напівпрозорий зливався з картою: крізь нього
     просвічували точки й підписи, текст ставав нечитабельним. Гасимо прозорість
     на всіх рівнях — і на обгортці, і на самому .leaflet-popup, бо Leaflet
     керує opacity контейнера через анімацію появи. */
  .leaflet-popup.pp{opacity:1!important}
  .pp .leaflet-popup-content-wrapper{background:#0f1720!important;opacity:1!important;
    border:1px solid #44586d;border-radius:9px;
    box-shadow:0 14px 48px rgba(0,0,0,.92), 0 0 0 6px rgba(6,9,16,.75)}
  .pp .leaflet-popup-tip{background:#0f1720!important;border:1px solid #44586d;
    opacity:1!important;box-shadow:none}
  .pp .leaflet-popup-content{background:#0f1720}
  .pp .leaflet-popup-content{margin:11px 13px;max-height:280px;overflow-y:auto}
  .pp a.leaflet-popup-close-button{color:#5b7c96}
</style></head><body>
<div id="wrap">
  <div id="map"></div><canvas class="fx" id="fx"></canvas>
  <div id="layers">
    <button id="layToggle">🎯 Обʼєкти</button>
    <div id="layPanel" hidden></div>
  </div>
  <div id="nav">
    <a href="../index.html">← Зведення</a>
    <a href="../day/__DATE__.html">Звіт за ніч</a>
    <a href="../nights.html">Усі ночі</a>
    <a href="../live.html">Що зараз</a>
    <span class=t>__DATE__ · дані до __BUILD__</span>
  </div>
  <div id="banner">
    <div id="clock">--:--</div><div id="phase"></div>
  </div>
  <div id="strip">
    <svg id="hist" preserveAspectRatio="none"></svg>
    <div id="ctrl">
      <button id="play" class="on">Пауза</button>
      <button data-s="60">60x</button><button data-s="120" class="on">120x</button>
      <button data-s="300">300x</button>
      <button id="restart">⟲</button>
    </div>
  </div>
</div>
<aside>
  <h1>__TITLE__</h1>
  <div class="sub">__SUB__</div>
  <div id="front"></div>
  <div id="ledger"></div>
  <div class="counters">
    <div class="c"><b id="cFix" style="color:var(--cyan)">0</b><span>ФІКСАЦІЙ</span></div>
    <div class="c"><b id="cDr" style="color:var(--fg)">0</b><span>АПАРАТІВ</span></div>
    <div class="c"><b id="cPvo" style="color:var(--red)">0</b><span>ППО+ЗБИТТЯ</span></div>
    <div class="c"><b id="cAl" style="color:var(--amber)">0</b><span>ОБЛ.ТРИВОГА</span></div>
  </div>
  <div class="hdr">Треки руху</div>
  <div id="tracks"></div>
  <div class="hdr">Стрічка</div>
  <div id="feed"></div>
  <div class="hdr">Що на карті</div>
  <div style="font-size:10px;color:#6d7f82;margin-bottom:8px;line-height:1.6">
    Символ = група спостережень поруч; цифра всередині — скільки апаратів
    заявлено, «·N» — скільки НП злилось. Зум розділяє групи.</div>
  <div class="legend">
    <div><i style="background:#38d4dd"></i><b>коло</b> — апарат бачили/чули
      <span id="lgFix"></span></div>
    <div><span style="color:#ff4d63;font-weight:700">◎</span> <b>кільце</b> — працює ППО
      <span id="lgPvo"></span></div>
    <div><span style="color:#fff;font-weight:700">✕</span> <b>хрест</b> — збито
      <span id="lgKill"></span></div>
    <div><span style="color:#ff8a1f;font-weight:700">★</span> <b>зірка</b> — вибух/приліт
      <span id="lgBoom"></span></div>
    <div><span style="color:#4ade80;font-weight:700">▲</span> <b>трикутник</b> — пуск</div>
    <div style="margin:7px 0 3px;color:#8fa3b6">розмір і цифра = скільки апаратів:</div>
    <div><svg width="150" height="26" style="vertical-align:middle">
      <circle cx="12" cy="14" r="7.4" fill="rgba(56,212,221,.2)" stroke="#5adce4"/>
      <circle cx="46" cy="14" r="9.9" fill="rgba(56,212,221,.2)" stroke="#5adce4"/>
      <circle cx="86" cy="14" r="11.6" fill="rgba(56,212,221,.2)" stroke="#5adce4"/>
      <circle cx="130" cy="14" r="14.8" fill="rgba(56,212,221,.2)" stroke="#5adce4"/>
      <text x="12" y="17" fill="#8fa3b6" font-size="8" text-anchor="middle">1</text>
      <text x="46" y="17" fill="#8fa3b6" font-size="8" text-anchor="middle">3</text>
      <text x="86" y="17" fill="#8fa3b6" font-size="8" text-anchor="middle">5</text>
      <text x="130" y="17" fill="#8fa3b6" font-size="8" text-anchor="middle">10</text>
    </svg></div>
    <div><span style="color:#be4660">▮</span> <b>область під тривогою</b> — рішення влади,
      саме по собі не означає що дрон там <span id="lgAlert"></span></div>
    <div><span style="color:#ff3c50">▮</span> <b>тривога + свіжі фіксації</b> — там реально щось є</div>
    <div><span style="color:var(--violet)">◗━</span> <b>об'єкт у русі</b> (трек)</div>
    <div><span style="color:#4a5b6c">┄┄</span> підконтрольна Україні територія (межа на рівні областей) — від неї рахується глибина</div>
    <div style="margin-top:6px;color:#55677a">розмір точки = заявлена кількість апаратів</div>
  </div>
  <div class="warnbox">__WARN__</div>
  <div class="note">__NOTE__</div>
</aside>
<script>
const RAID=__DATA__;
const EV=RAID.events.filter(e=>e.lat), TRK=(RAID.tracks||[]);
// Час парситься ОДИН раз. Раніше `new Date(e.t).getTime()` викликався в кожному
// фільтрі кожного кадру — тисячі разових парсів рядка на кадр, головний лаг.
EV.forEach(e=>e.ms=new Date(e.t).getTime());
const T0=new Date(EV[0].t).getTime(), T1=new Date(EV[EV.length-1].t).getTime(), SPAN=T1-T0;
const PULSE=90*1000;        // життя імпульсу, модельний час
const TRAIL=25*60*1000;     // довжина хвоста комети

// zoomAnimation вимкнено свідомо: Leaflet анімує тайли CSS-трансформом, а наше
// полотно малюється в координатах контейнера. Під час анімації одне їде, друге
// стоїть — картинка смикається. Без анімації зум клацає в нову позицію, і всі
// шари лишаються синхронними.
const map=L.map('map',{zoomControl:true,zoomAnimation:false,
                       markerZoomAnimation:false,fadeAnimation:false}).setView([52,38],5);
// Підкладка — Esri Dark Gray, без ключа. CARTO (dark_nolabels) з вересня
// 2026 віддає на кожній плитці водяний знак «API KEY REQUIRED», зокрема й з
// Referer продакшну: публічна карта йшла ним поцяткована.
const ESRI='https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/';
L.tileLayer(ESRI+'World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}',
  {attribution:'&copy; Esri, HERE, Garmin, &copy; OpenStreetMap',maxZoom:11,opacity:.55}).addTo(map);
L.tileLayer(ESRI+'World_Dark_Gray_Reference/MapServer/tile/{z}/{y}/{x}',
  {maxZoom:11,opacity:.45}).addTo(map);
const q=(a,p)=>a.slice().sort((x,y)=>x-y)[Math.floor(a.length*p)];
const la=EV.map(e=>e.lat), ln=EV.map(e=>e.lon);
map.fitBounds([[q(la,.04),q(ln,.04)],[q(la,.96),q(ln,.96)]],{padding:[40,70],maxZoom:7});
__UA_RINGS__.forEach(r=>L.polyline(r,{color:'#4a5b6c',weight:1.6,dashArray:'8 8',interactive:false}).addTo(map));

const RG=RAID.region_geo||{};
let POLY={};

// Точкові спостереження групуємо по НП; вузол не зникає, лише холоне.
//
// Мова форми — як у редакторі (mapper/mknight.sightings): крапка — місце,
// порожнє кільце — площа. Центр ОБЛАСТІ (centroid, region-snap) крапкою
// брехав: «Пуски БПЛА от Одесской области» ставали кружком у центрі Одещини,
// «Брянская область / Фиксация БПЛА» — точкою під Брянськом (BACKLOG §13.1).
// Такі події на карту місцем не йдуть — область і так підсвічується шаром
// тривог (hotIn рахує їх). Виняток — пуск: його джерело найчастіше ціла
// область, і він малюється кільцем, як центр району чи здогад без області.
const AREA_NAME=/\b(?:rayon|raion|district|okrug|oblast|miskrada|hromada)\b|округ|район|(^|\s)ГО(\s|$)/i;
const areaOf=e=>{
  const fb=e.geo_conf==='centroid'||e.geo_conf==='region-snap';
  if(fb) return e.kind==='пуск'?'область':null;
  // Пост назвав лише, КУДИ летять («в направлении Каланчак»): крапка на цілі,
  // але це не місце спостереження (поле `aim`, сховище v21).
  if(e.aim) return 'ціль';
  if(e.area||AREA_NAME.test(e.place||'')) return 'район';
  if(e.geo_conf==='global') return 'здогад';
  return '';
};
const onMap=e=>e.scope==='точка'&&areaOf(e)!==null;
const places=new Map();
EV.filter(onMap).forEach(e=>{
  const k=e.place+'|'+e.lat.toFixed(3);
  if(!places.has(k)) places.set(k,{lat:e.lat,lon:e.lon,name:e.place,region:e.region,ev:[],area:areaOf(e)});
  const pl=places.get(k); pl.ev.push(e);
  if(!areaOf(e)) pl.area='';      // хоч одне справжнє розвʼязання — це місце
});
// Площа чи місце — за подіями, які вже ВІДБУЛИСЬ на цей момент: інакше місце
// ставало суцільним ще до своєї першої справжньої події.
const areaNow=(pl,now)=>pl.ev.every(e=>e.ms>now||areaOf(e));
const PT=[...places.values()];

// Тривоги — це СТАН області в часі: вмикається на тривозі, гасне на відбої.
// Будуємо інтервали заздалегідь, щоб на кожному кадрі лише зчитувати.
const alerts=new Map();
EV.filter(e=>e.scope!=='точка'&&e.region).forEach(e=>{
  if(!alerts.has(e.region)) alerts.set(e.region,[]);
  alerts.get(e.region).push({t:new Date(e.t).getTime(),on:e.kind!=='відбій'});
});
alerts.forEach(v=>v.sort((a,b)=>a.t-b.t));
function hotIn(reg,now){
  // «гаряча» = за останні 45 хв в області було хоч одне точкове спостереження
  const W=45*60*1000;
  return EV.some(e=>e.region===reg&&e.scope==='точка'&&
                    now-new Date(e.t).getTime()<W&&new Date(e.t).getTime()<=now);
}
function alertState(now){
  const out=[];
  for(const [reg,list] of alerts){
    let on=false, last=0;
    for(const x of list){ if(x.t>now) break; on=x.on; last=x.t; }
    if(!on) continue;
    const fade=Math.max(.35,1-(now-last)/(3*60*60*1000));   // старіє, не зникає різко
    out.push([reg,fade]);
  }
  return out;
}

// --- ШАР 3: комети. Позиція інтерполюється за часом уздовж треку ------------
const tracks=TRK.map(t=>({...t,
  pts:t.points.map(p=>({t:new Date(p.t).getTime(),lat:p.lat,lon:p.lon,place:p.place})),
  a:new Date(t.t0).getTime(), b:new Date(t.t1).getTime()}));
function posAt(tr,now){
  if(now<tr.a||now>tr.b) return null;
  const p=tr.pts;
  for(let i=0;i<p.length-1;i++){
    if(now>=p[i].t&&now<=p[i+1].t){
      const k=(now-p[i].t)/(p[i+1].t-p[i].t||1);
      return [p[i].lat+(p[i+1].lat-p[i].lat)*k, p[i].lon+(p[i+1].lon-p[i].lon)*k];
    }
  }
  return [p[p.length-1].lat,p[p.length-1].lon];
}
function pathBetween(tr,from,to){
  const out=[]; const p=tr.pts;
  const s=posAt(tr,Math.max(from,tr.a)); if(s) out.push(s);
  p.forEach(x=>{ if(x.t>from&&x.t<to) out.push([x.lat,x.lon]); });
  const e=posAt(tr,to); if(e) out.push(e);
  return out;
}

// --- малювання на canvas поверх карти --------------------------------------
const fx=document.getElementById('fx'), ctx=fx.getContext('2d');
function resize(){const r=fx.getBoundingClientRect();
  fx.width=r.width*devicePixelRatio; fx.height=r.height*devicePixelRatio;
  ctx.setTransform(devicePixelRatio,0,0,devicePixelRatio,0,0);}
addEventListener('resize',resize); resize();
const P=(lat,lon)=>{const p=map.latLngToContainerPoint([lat,lon]);return[p.x,p.y];};

let now=T0, speed=120, playing=true, sel=null;

function draw(){
  const r=fx.getBoundingClientRect();
  ctx.clearRect(0,0,r.width,r.height);

  // ---- ШАР 0: області ------------------------------------------------------
  // Тривога — це СТАН цілої області, тому вона й малюється як область.
  // Раніше тут була пляма по центроїду: вона не збігалася з реальними межами
  // і читалась як «щось у цій точці», хоча означає зовсім інше.
  const path=rings=>{
    ctx.beginPath();
    rings.forEach(ring=>{
      ring.forEach(([la,lo],i)=>{const [x,y]=P(la,lo); i?ctx.lineTo(x,y):ctx.moveTo(x,y);});
      ctx.closePath();
    });
  };
  // контури всіх відомих областей — щоб географія читалась завжди
  ctx.lineWidth=.6; ctx.strokeStyle='rgba(120,150,180,.13)';
  for(const k in POLY){ path(POLY[k]); ctx.stroke(); }

  const AL=new Map(alertState(now));
  for(const [reg,st] of AL){
    const rings=POLY[reg]; if(!rings) continue;
    // насиченість = чи є в області СВІЖІ фіксації. Сама тривога — блідий фон,
    // тривога плюс реальні спостереження — насичений червоний.
    const hot=hotIn(reg,now);
    path(rings);
    // Контраст навмисно різкий: під тривогою півкраїни, і якби всі області
    // заливались однаково, карта була б суцільно червоною і безінформативною.
    // Бліде — «оголошено тривогу». Насичене — «тривога І свіжі фіксації».
    path(rings);
    // Тривога — це ФОН, а не головний обʼєкт. Заливка ледь помітна, акцент на
    // контурі: інакше червоні площі перебивають самі спостереження.
    ctx.fillStyle=hot?`rgba(255,48,70,${.13*st})`:`rgba(150,60,80,${.03*st})`;
    ctx.fill();
    ctx.lineWidth=hot?1.6:.7;
    ctx.strokeStyle=hot?`rgba(255,105,120,${.70*st})`:`rgba(150,85,105,${.16*st})`;
    ctx.stroke();
  }

  // ---- ШАР 1: спостереження, ЗІБРАНІ В КЛАСТЕРИ ---------------------------
  // Раніше малювалась кожна з ~275 точок окремо. На масштабі країни вони
  // накладались одна на одну, цифри висіли окремо від кружків, і карта
  // перетворювалась на кашу. Тепер точки збираються в комірки по 46 пікселів:
  // один символ на комірку, розмір за сумою апаратів. При зумі комірка
  // покриває меншу територію — кластери самі розпадаються на окремі НП.
  const CELL=46, COOL=2*60*60*1000;
  const cells=new Map();
  PT.forEach(pl=>{
    const seen=pl.ev.filter(e=>e.ms<=now);
    if(!seen.length) return;
    const [x,y]=P(pl.lat,pl.lon);
    if(x<-80||y<-80||x>r.width+80||y>r.height+80) return;   // поза екраном
    const key=Math.round(x/CELL)+':'+Math.round(y/CELL);
    let c=cells.get(key);
    if(!c){c={x:0,y:0,w:0,n:0,drones:0,last:0,kinds:new Set(),places:0,solid:0,aim:0};cells.set(key,c);}
    if(!areaNow(pl,now)) c.solid++;
    else if(seen.every(e=>areaOf(e)==='ціль')) c.aim++;
    const drones=seen.reduce((m,e)=>Math.max(m,e.drones||0),0);
    const wgt=1+drones;
    c.x+=x*wgt; c.y+=y*wgt; c.w+=wgt;        // центр ваги, не центр комірки
    c.n+=seen.length; c.drones+=drones; c.places++;
    seen.forEach(e=>c.kinds.add(e.kind));
    c.last=Math.max(c.last,...seen.map(e=>e.ms));
  });

  const R_OF=n=>4.5+Math.sqrt(Math.max(1,n))*3.2;
  const order=['вибух','збиття','ППО','пуск','фіксація'];
  [...cells.values()].sort((a,b)=>a.drones-b.drones).forEach(c=>{
    const x=c.x/c.w, y=c.y/c.w;
    const h=Math.max(0,1-(now-c.last)/COOL);          // свіжість
    const kind=order.find(k=>c.kinds.has(k))||'фіксація';
    const rad=R_OF(c.drones||c.n);

    if(!c.solid&&c.aim===c.places){
      // Лише цілі руху: знак прицілу (кільце й чотири риски) — «сюди летять».
      // Не крапка («тут бачили») і не стрілка (звідки летять, пост не каже).
      // Так само в редакторі.
      const col=kind==='пуск'?'74,222,128':kind==='ППО'||kind==='збиття'?'255,77,99'
               :kind==='вибух'?'255,138,31':'90,220,228';
      const rr=Math.max(6,rad*.7), t0=rr-2.5, t1=rr+6;
      const ring=(w,st)=>{ctx.lineWidth=w;ctx.strokeStyle=st;
        ctx.beginPath();ctx.arc(x,y,rr,0,7);ctx.stroke();
        ctx.beginPath();
        for(const [dx,dy] of [[0,-1],[1,0],[0,1],[-1,0]]){
          ctx.moveTo(x+dx*t0,y+dy*t0);ctx.lineTo(x+dx*t1,y+dy*t1);}
        ctx.stroke();};
      ring(3.4,'rgba(4,7,12,.75)');
      ring(1.6,`rgba(${col},${.6+.35*h})`);
    } else if(!c.solid){
      // лише площі (область-джерело пуску, центр району, здогад) — порожнє
      // кільце кольору виду, як у редакторі; крапка тут означала б місце
      const col=kind==='пуск'?'74,222,128':kind==='ППО'||kind==='збиття'?'255,77,99'
               :kind==='вибух'?'255,138,31':'90,220,228';
      // Пунктир: у плеєрі й фіксація — кільце з ледь помітною заливкою, тож
      // суцільне порожнє кільце від неї на око не відрізнялось.
      ctx.beginPath(); ctx.arc(x,y,rad,0,7);
      ctx.lineWidth=3; ctx.strokeStyle='rgba(4,7,12,.7)'; ctx.stroke();
      ctx.setLineDash([4,3]);
      ctx.lineWidth=1.6; ctx.strokeStyle=`rgba(${col},${.5+.45*h})`; ctx.stroke();
      ctx.setLineDash([]);
    } else if(kind==='вибух'){
      ctx.beginPath();
      for(let i=0;i<10;i++){const a2=i*Math.PI/5-Math.PI/2, rr=i%2?rad*.45:rad+5;
        ctx[i?'lineTo':'moveTo'](x+Math.cos(a2)*rr,y+Math.sin(a2)*rr);}
      ctx.closePath(); ctx.fillStyle=`rgba(255,138,31,${.5+.4*h})`; ctx.fill();
    } else if(kind==='збиття'){
      ctx.lineWidth=2.4; ctx.strokeStyle=`rgba(255,255,255,${.55+.4*h})`;
      const d=rad; ctx.beginPath();
      ctx.moveTo(x-d,y-d);ctx.lineTo(x+d,y+d);ctx.moveTo(x+d,y-d);ctx.lineTo(x-d,y+d);ctx.stroke();
    } else if(kind==='ППО'){
      ctx.beginPath(); ctx.arc(x,y,rad,0,7);
      ctx.lineWidth=2.4; ctx.strokeStyle=`rgba(255,77,99,${.5+.45*h})`; ctx.stroke();
      ctx.beginPath(); ctx.arc(x,y,rad*.3,0,7);
      ctx.fillStyle=`rgba(255,77,99,${.5+.4*h})`; ctx.fill();
    } else if(kind==='пуск'){
      ctx.beginPath(); ctx.moveTo(x,y-rad);ctx.lineTo(x+rad*.9,y+rad*.7);
      ctx.lineTo(x-rad*.9,y+rad*.7); ctx.closePath();
      ctx.fillStyle=`rgba(74,222,128,${.5+.4*h})`; ctx.fill();
    } else {
      ctx.beginPath(); ctx.arc(x,y,rad,0,7);
      ctx.fillStyle=`rgba(56,212,221,${.07+.20*h})`; ctx.fill();
      ctx.lineWidth=1.2+h; ctx.strokeStyle=`rgba(90,220,228,${.22+.55*h})`; ctx.stroke();
    }
    // Цифра ВСЕРЕДИНІ символу, а не збоку: інакше при щільності незрозуміло,
    // до якого кружка вона належить.
    if(c.drones>=3){
      ctx.font=`600 ${Math.min(14,9+c.drones/4)}px ui-monospace,monospace`;
      ctx.textAlign='center'; ctx.textBaseline='middle';
      ctx.lineWidth=3.2; ctx.strokeStyle='rgba(6,9,16,.92)';
      ctx.strokeText(String(c.drones),x,y);
      ctx.fillStyle=`rgba(240,250,255,${.6+.4*h})`;
      ctx.fillText(String(c.drones),x,y);
      ctx.textAlign='left'; ctx.textBaseline='alphabetic';
    }
    // Скільки НП злилось у цей символ — щоб було видно, що це група
    if(c.places>1 && c.drones<3){
      ctx.font='9px ui-monospace,monospace'; ctx.textAlign='center';
      ctx.fillStyle=`rgba(150,175,195,${.35+.35*h})`;
      ctx.fillText('·'+c.places,x,y+3); ctx.textAlign='left';
    }
  });
  window.__cells=cells;

  // ---- вибрана точка: суцільне кільце, щоб було видно ЩО саме відкрито -----
  if(sel){
    const [x,y]=P(sel.lat,sel.lon);
    ctx.beginPath(); ctx.arc(x,y,17,0,7);
    ctx.lineWidth=2; ctx.strokeStyle='rgba(255,255,255,.9)'; ctx.stroke();
    ctx.beginPath(); ctx.arc(x,y,21,0,7);
    ctx.lineWidth=1; ctx.strokeStyle='rgba(255,255,255,.35)'; ctx.stroke();
  }

  // ---- ШАР 2: імпульс щойної події ----------------------------------------
  EV.forEach(e=>{
    if(!onMap(e)) return;
    const ts=e.ms, age=now-ts;
    if(age<0||age>PULSE) return;
    const k=age/PULSE, [x,y]=P(e.lat,e.lon);
    const col=e.kind==='ППО'||e.kind==='збиття'?'255,77,99'
             :e.kind==='вибух'?'255,138,31':'56,212,221';
    ctx.beginPath(); ctx.arc(x,y,5+k*30,0,7);
    ctx.lineWidth=2.2*(1-k); ctx.strokeStyle=`rgba(${col},${.85*(1-k)})`; ctx.stroke();
  });

  // ---- ШАР 3: комети ------------------------------------------------------
  tracks.forEach(tr=>{
    const pos=posAt(tr,now); if(!pos) return;
    const tail=pathBetween(tr,now-TRAIL,now);
    for(let i=0;i<tail.length-1;i++){
      const k=i/(tail.length-1);
      const [x1,y1]=P(...tail[i]), [x2,y2]=P(...tail[i+1]);
      ctx.beginPath(); ctx.moveTo(x1,y1); ctx.lineTo(x2,y2);
      ctx.lineWidth=1.5+3.5*k; ctx.strokeStyle=`rgba(167,139,250,${.12+.75*k})`; ctx.stroke();
    }
    const [hx,hy]=P(...pos);
    ctx.beginPath(); ctx.arc(hx,hy,16,0,7); ctx.fillStyle='rgba(167,139,250,.10)'; ctx.fill();
    ctx.beginPath(); ctx.arc(hx,hy,8,0,7);  ctx.fillStyle='rgba(167,139,250,.28)'; ctx.fill();
    ctx.beginPath(); ctx.arc(hx,hy,4,0,7);  ctx.fillStyle='#fff'; ctx.fill();
    ctx.font='10px ui-monospace,monospace'; ctx.fillStyle='rgba(214,201,255,.9)';
    ctx.fillText(`${tr.kmh} км/год`,hx+12,hy-8);
  });

  drawTargets();        // цілі поверх подій, на тому ж canvas
}

// --- смуга часу ------------------------------------------------------------
const BIN=15*60*1000, bins=new Map();
EV.filter(e=>e.scope==='точка').forEach(e=>{const b=Math.floor((e.ms-T0)/BIN); bins.set(b,(bins.get(b)||0)+1);});
const nb=Math.ceil(SPAN/BIN), mx=Math.max(...bins.values());
const hist=document.getElementById('hist');
hist.setAttribute('viewBox',`0 0 ${nb} 40`);
hist.innerHTML=Array.from({length:nb},(_,i)=>{
  const v=bins.get(i)||0, h=v/mx*36;
  return `<rect x="${i+.12}" y="${38-h}" width=".76" height="${h}" fill="#1d4a56"/>`;
}).join('')+`<rect id="ph" x="0" y="0" width=".22" height="40" fill="#38d4dd"/>`;
const ph=document.getElementById('ph');

// --- панель ----------------------------------------------------------------
function panel(){
  // Один прохід замість шести EV.filter: усі лічильники рахуються разом.
  let fix=0,pvo=0,boom=0,kill=0,drones=0; const seen=[],places=new Set(),
    regs=new Set(),recent=[];
  for(const e of EV){
    if(e.ms>now) continue;
    seen.push(e);
    if(e.kind==='фіксація') fix++;
    else if(e.kind==='збиття'){pvo++;kill++;}
    else if(e.kind==='ППО') pvo++;
    else if(e.kind==='вибух') boom++;
    drones+=e.drones||0;
    if(e.region) regs.add(e.region);
    if(onMap(e)){ places.add(e.place);
      if(now-e.ms<3600000) recent.push(e.depth); }
  }
  const pl=places.size;
  const alertsNow=alertState(now).length;
  const live=tracks.filter(t=>posAt(t,now));
  recent.sort((a,b)=>a-b);
  const deep=recent.length?recent[Math.floor(recent.length*0.9)]:0;
  document.getElementById('clock').textContent=
    new Date(now).toLocaleTimeString('uk-UA',{hour:'2-digit',minute:'2-digit'})+' МСК';
  const last=seen[seen.length-1];
  document.getElementById('phase').textContent = live.length
    ? `${live.length} об'єкт(и) у русі · ${live[0].from} → ${live[0].to}`
    : (last?`${last.place||''} — ${last.kind}`:'');
  document.getElementById('front').textContent=
    `фронт за останню годину: ${deep} км вглиб · ${pl} НП зі спостереженнями · `+
    `${alertsNow} обл. під тривогою · заявлено ${drones} апаратів`;
  document.getElementById('cFix').textContent=fix;
  document.getElementById('cDr').textContent=drones;
  document.getElementById('cPvo').textContent=pvo;
  document.getElementById('cAl').textContent=alertsNow;
  document.getElementById('ledger').innerHTML=
    `<span style="color:#38d4dd">заявлено <b>${drones}</b> апаратів</span>`+
    `<span style="color:#68798c"> · </span>`+
    `<span style="color:#ff8fa0">ППО <b>${pvo-kill}</b></span>`+
    `<span style="color:#68798c"> · </span>`+
    `<span style="color:#fff">збито <b>${kill}</b></span>`+
    `<span style="color:#68798c"> · </span>`+
    `<span style="color:#ff8a1f">вибухів <b>${boom}</b></span>`;
  const lg=(id,v)=>document.getElementById(id).textContent=v?`· ${v}`:'';
  lg('lgFix',fix); lg('lgPvo',pvo-kill); lg('lgKill',kill); lg('lgBoom',boom);
  lg('lgAlert',alertsNow);
  document.getElementById('feed').innerHTML=seen.slice(-10).reverse().map(e=>{
    // Тип засобу — поруч із видом: «пуск» без «чим» каже половину. Пуск
    // Storm Shadow — це крилаті ракети, пуск БпЛА — дрони, і читач плеєра
    // досі бачив однакове «пуск». Колір знака на карті тип НЕ кодує: він
    // кодує вид події, і змішувати два виміри в одному кольорі не можна.
    const cls={'ППО':'pvo','збиття':'pvo','вибух':'pvo','фіксація':'fix',
               'тривога':'warn','відбій':'off'}[e.kind]||'';
    return `<div class="ev ${cls}"><time>${esc(e.hhmm)}</time><span class="km">${esc(e.depth)} км</span>
      <b style="color:#96a8ba">${esc(e.kind)}</b>${e.utype?` <span style="color:#c9d6e3">· ${esc(e.utype)}</span>`:''} ${esc(e.place)}
      <div style="color:var(--dim)">${esc((e.text||'').slice(0,72))}</div>
      <a href="${esc(e.url)}" target="_blank">джерело ↗</a></div>`;}).join('');
  document.getElementById('tracks').innerHTML=tracks.map((tr,i)=>{
    const st=now<tr.a?'':(now>tr.b?'done':'live');
    return `<div class="trk ${st}" data-i="${i}">
      <b>${esc((tr.from||'').slice(0,12))} → ${esc((tr.to||'').slice(0,12))}</b>
      <span>${esc(tr.km)}км ${esc(tr.kmh)}км/г</span></div>`;}).join('');
  document.querySelectorAll('.trk').forEach(el=>el.onclick=()=>{
    const tr=tracks[+el.dataset.i]; now=tr.a; sync();
    map.fitBounds(tr.pts.map(p=>[p.lat,p.lon]),{padding:[70,70]});
  });
  ph.setAttribute('x',(now-T0)/SPAN*nb);
}
// Розділення частот — ключ до плавності:
//   draw()  — canvas, дешевий, потрібен щокадру для анімації комет/імпульсів
//   panel() — перебудова DOM (стрічка, треки, лічильники), ДОРОГА. Оновлюється
//             ~6 разів/сек, бо стрічка подій не мусить смикатись 60 разів.
let lastPanel=0;
function sync(force){ draw(); panel(); lastPanel=performance.now(); }

let prev=performance.now(), rafId=0;
function loop(ts){
  const dt=ts-prev; prev=ts;
  if(!playing){ rafId=0; return; }           // на паузі RAF не крутиться взагалі
  now+=dt*speed;
  if(now>=T1){now=T1;playing=false;document.getElementById('play').textContent='Старт';}
  draw();                                     // canvas щокадру — плавна анімація
  if(ts-lastPanel>160){ panel(); lastPanel=ts; }   // DOM ~6 разів/сек
  rafId=requestAnimationFrame(loop);
}
function start(){ if(!rafId){ prev=performance.now(); rafId=requestAnimationFrame(loop); } }
// Перетягування/зум карти: перемалювати лише canvas (дешево), без DOM.
map.on('move zoom zoomend moveend resize',draw);
document.getElementById('play').onclick=e=>{
  if(now>=T1) now=T0;
  playing=!playing; e.target.textContent=playing?'Пауза':'Старт';
  if(playing) start(); else sync();};        // пауза = один фінальний sync, тоді тиша
document.getElementById('restart').onclick=()=>{now=T0;sync();};
document.querySelectorAll('[data-s]').forEach(b=>b.onclick=()=>{
  speed=+b.dataset.s;
  document.querySelectorAll('[data-s]').forEach(x=>x.classList.remove('on'));b.classList.add('on');});
document.getElementById('strip').addEventListener('click',ev=>{
  if(ev.target.closest('#ctrl')) return;
  const r=hist.getBoundingClientRect();
  now=T0+Math.max(0,Math.min(1,(ev.clientX-r.left)/r.width))*SPAN; sync();});

// ---- влучання по точках ----------------------------------------------------
// Полотно має pointer-events:none, щоб не блокувати перетягування карти, тож
// клік ловимо на самій карті й самі шукаємо найближчий вузол.
const HIT=14;
function nearest(latlng){
  const c=map.latLngToContainerPoint(latlng);
  let best=null,bd=HIT;
  PT.forEach(pl=>{
    if(!pl.ev.some(e=>e.ms<=now)) return;
    const p=map.latLngToContainerPoint([pl.lat,pl.lon]);
    const d=Math.hypot(p.x-c.x,p.y-c.y);
    if(d<bd){bd=d;best=pl;}
  });
  return best;
}
// Екранує все, що йде в innerHTML. Лапки теж: частина вставок — в атрибути
// (href="${...}"), і без них чужий рядок вийшов би з атрибута.
// Текст постів пишуть у публічних каналах, назви обʼєктів — будь-хто в OSM,
// назви НП — GeoNames. Жодне з цього не наше.
function esc(t){return String(t==null?'':t).replace(/[&<>"']/g,
  ch=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));}
map.on('click',ev=>{
  // Спершу — ціль-обʼєкт (якщо шар увімкнено й клік влучив у значок).
  const to=nearestTarget(ev.latlng);
  if(to){
    const col=TARGETS.colors[to.cat]||'#8899aa';
    const t=to.osm?(to.osm[0]==='n'?'node':to.osm[0]==='w'?'way':'relation'):'';
    L.popup({maxWidth:300,className:'pp'}).setLatLng([to.lat,to.lon])
     .setContent(`<div style="font:12px ui-monospace,monospace;color:#dbe6f0">`+
       `<b style="color:${col}">${T_GLYPH[to.cat]||''} ${esc(T_LABEL[to.cat]||to.cat)}</b>`+
       `<br>${esc(to.name)||'(без назви)'}`+
       (to.osm?`<br><a href="https://www.openstreetmap.org/${t}/${esc(to.osm.slice(1))}" `+
         `target=_blank style="color:#5b7c96;font-size:10px">OSM ↗</a>`
        :`<br><span style="color:#7d8a5a;font-size:10px">курований · координати приблизні</span>`)+
       `</div>`).openOn(map);
    return;
  }
  const pl=nearest(ev.latlng); if(!pl){sel=null;draw();return;}
  sel=pl;
  const seen=pl.ev.filter(e=>e.ms<=now)
                  .sort((a,b)=>new Date(b.t)-new Date(a.t));
  const dr=seen.reduce((a,e)=>a+(e.drones||0),0);
  const T_UA={refinery:'НПЗ',airfield:'аеродром',ammo_depot:'склад БК',
    defense_plant:'оборонний завод',chemical:'хімія',fuel_depot:'нафтобаза',
    naval:'ВМБ',military_base:'військова зона',range:'полігон'};
  // Сусідство рахуємо ТУТ, із targets.json, а не беремо поле near з події.
  //
  // Поле near називало ОДИН обʼєкт так, ніби подія з ним повʼязана. Заміряно
  // 20.09.2026 на сховищі з 2026-04-18: у 68% привʼязок у радіусі стояло 6+
  // цілей, у 51% — нічия в тому самому ярусі пріоритету, тож обирала відстань
  // до центру НП. Текст події називав обʼєкт (НПЗ, аеродром, склад) лише в
  // 1.2% випадків: «Тула / Работа ПВО по БПЛА» діставало «поблизу: Клокове,
  // 5 км». І сама відстань була вигаданою точністю — вона рахується від
  // ЦЕНТРОЇДА НП, а не від місця події, якого ми не знаємо.
  //
  // Тому тепер: геометрія, названа геометрією. Один обʼєкт у радіусі — можна
  // назвати, бо вибору нема; кілька — лише число й типи, без імені. Стеля
  // показана числом, а не прикрита вибором навмання.
  //
  // Крапка-фолбек (centroid/region-snap) рядка не отримує взагалі: там
  // координата — центр області, а не місце, і «в радіусі 15 км» від неї не
  // означає нічого. conf="region" сюди НЕ входить, хоч і лежить у
  // store.REGIONAL_FALLBACK: це повноцінне розвʼязання топоніма всередині
  // названої області, і крапка в нього справжня.
  // Ярус 1-2, без тла. Перша версія рахувала ВСІ обʼєкти, і замір показав, що
  // 86.5% порахованого — ярус 3, тобто «військові зони» й полігони з OSM, які
  // карта сама не малює до зуму 7. Із 489 крапок, де рядок називав один
  // обʼєкт, 353 називали саме це тло («Міський військкомат»). Той самий поріг
  // уже стоїть у mapper/mktargets.py для пошуку в редакторі.
  //
  // Заміряно (вересень, 3747 крапок-днів): з тлом рядок на 51.2% крапок,
  // медіана 4 обʼєкти в радіусі, p90 29, макс 251, конкретне імʼя в 25%
  // рядків. Без тла — 29.4%, медіана 1, p90 5, макс 41, імʼя у 50% рядків,
  // і це аеродроми, нафтобази, склади БК, НПЗ.
  // Площа (центр району, здогад, область-джерело пуску) рядка теж не має:
  // «у радіусі 15 км» від центроїда району означає так само мало.
  const around=(seen.every(e=>areaOf(e))
      ? [] : (TARGETS.objects||[]).filter(x=>x.lat!=null && (x.tier||3)<=2
          && map.distance([pl.lat,pl.lon],[x.lat,x.lon])<=NEAR_R*1000));
  const byCat={};
  around.forEach(x=>{byCat[x.cat]=(byCat[x.cat]||0)+1;});
  // Саме `o`, а не `around[0]`: назва обʼєкта — сирий тег OSM, і
  // test_makeraid_near_line_escapes_osm_name стереже вставку за ІМЕНЕМ
  // змінної. Через `around[0].name` детектор проходив повз, і тест зеленів,
  // нічого не перевіривши — спіймано контрольним прогоном 20.09.2026.
  const o=around.length===1?around[0]:null;
  const nearBody=o
    ? `у радіусі ${NEAR_R} км один відомий обʼєкт: `+
      `${esc(o.name||T_UA[o.cat]||o.cat)} (${esc(T_UA[o.cat]||o.cat)})`
    : around.length>1
    ? `у радіусі ${NEAR_R} км відомих обʼєктів: ${around.length} — `+
      Object.entries(byCat).sort((a,b)=>b[1]-a[1]).slice(0,3)
        .map(kv=>`${esc(T_UA[kv[0]]||kv[0])} ×${kv[1]}`).join(', ')
    : '';
  const nearLine=nearBody?`<div style="color:#8ea0b2;font-size:11px;margin:4px 0">`+
    `⌖ ${nearBody}</div>`:'';
  const rows=seen.slice(0,8).map(e=>
    `<div style="margin:3px 0;padding-left:7px;border-left:2px solid #2b3b4c">
       <b style="color:#38d4dd">${esc(e.hhmm)}</b>
       <span style="color:#ff9db0">${esc(e.kind)}</span>${e.utype?` · <span style="color:#c9d6e3">${esc(e.utype)}</span>`:''}${e.drones?` · ${esc(e.drones)} апаратів`:''}
       <div style="color:#8ea0b2;font-size:11px">${esc((e.text||'').slice(0,150))}</div>
       <a href="${esc(e.url)}" target="_blank" style="color:#5b7c96;font-size:10px">джерело ↗</a>
     </div>`).join('');
  L.popup({maxWidth:340,className:'pp'})
   .setLatLng([pl.lat,pl.lon])
   .setContent(`<div style="font:12px ui-monospace,monospace;color:#dbe6f0">
      <div style="font-size:13px;margin-bottom:4px"><b>${esc(pl.name)}</b>
        <span style="color:#7a8b9c">${esc(pl.region||'')}</span></div>
      ${seen.every(e=>areaOf(e)==='ціль')?`<div style="color:#c9d6e3;margin-bottom:4px">`+
        `курс сюди — де саме бачили, пости не кажуть</div>`:''}
      <div style="color:#7a8b9c;margin-bottom:6px">${seen.length} повідомлень${
        dr?` · заявлено ${dr} апаратів`:''}${seen.length>8?' · показано 8 останніх':''}</div>
      ${nearLine}${rows}</div>`)
   .openOn(map);
  draw();
});
map.on('popupclose',()=>{sel=null;draw();});
map.on('mousemove',ev=>{
  map.getContainer().style.cursor=(nearestTarget(ev.latlng)||nearest(ev.latlng))?'pointer':'';
});

// ---- ШАР ОБʼЄКТІВ (військові + промислові цілі) ---------------------------
// Цілі тягнуться окремим файлом, а не вшиваються в сторінку. Причина не лише
// у вазі (656 КБ = 52% сторінки, ×30 сторінок ≈ 19 МБ дубля, який браузер не
// кешує між добами). Головне — вшита копія робила сторінку ЗАМОРОЖЕНИМ
// знімком targets.json на день збірки: cron перебудовує лише останні 10 діб,
// тому після кожного rank_targets.py архів розʼїжджався — той самий обʼєкт мав
// різну назву й вагу залежно від того, яку дату відкрив. Спільний файл робить
// таку розбіжність неможливою: усі сторінки читають один актуальний список.
let TARGETS={colors:{},objects:[]};
const T_LABEL={airfield:'Аеродроми',military_base:'Військові бази',
  range:'Полігони',ammo_depot:'Склади БК',naval:'ВМБ / порти',
  refinery:'НПЗ',fuel_depot:'Нафтобази / ПММ',chemical:'Хімія',
  defense_plant:'Оборонні заводи'};
const tCounts={};
const tActive=new Set();
const T_GLYPH={airfield:'✈',military_base:'▦',range:'◎',ammo_depot:'✷',
  naval:'⚓',refinery:'⬢',fuel_depot:'▮',chemical:'⚗',defense_plant:'⚙'};

// Обʼєкти малюються на ТОМУ Ж canvas, що й події. Раніше це були Leaflet-
// маркери (DOM-ноди); 4600 DOM-нодів вбили б браузер, тому стояла стеля «перші
// 1200» — і при зумі-аут решта просто зникала («обрізані цілі»). Canvas тримає
// тисячі значків за мілісекунди, стеля не потрібна, нічого не обрізається.
// Зум-gating за ярусом: стратегічні цілі (T1) видно завжди; паливна
// інфраструктура (T2) — від зуму 5; тло з тисяч баз/полігонів (T3) — від 7.
// Так на далекому зумі видно лише важливе, а не стіну з військових зон.
// Радіус, у якому попап рахує сусідні обʼєкти. 15 км — бо саме стільки
// покривала стара привʼязка: медіана відстані подія->ціль 5.2 км, p90 11.2 км
// (замір 20.09.2026). Це НЕ радіуси store.TARGET_PRIORITY: ті обирають одну
// ціль для рейтингу, а тут ми нічого не обираємо, лише рахуємо.
const NEAR_R=15;
const TIER_ZOOM={1:0, 2:5, 3:7};
function drawTargets(){
  if(!tActive.size){ document.getElementById('layToggle').textContent='🎯 Обʼєкти'; return; }
  const b=map.getBounds().pad(0.35);
  const z=map.getZoom();
  let shown=0, active=0, hidden=0;
  for(const o of TARGETS.objects){
    if(!tActive.has(o.cat)) continue;
    active++;
    if(z < (TIER_ZOOM[o.tier||3]||0)){ hidden++; continue; }   // ярус ще не час
    if(!b.contains([o.lat,o.lon])) continue;
    shown++;
    const col=TARGETS.colors[o.cat]||'#8899aa';
    const [x,y]=P(o.lat,o.lon);
    const imp=o.imp||0.3;
    // Розмір і яскравість за важливістю: гаряча стратегічна ціль велика й
    // яскрава, фонова база — дрібна й тьмяна.
    const r=3+imp*5, a=0.35+imp*0.6;
    const detailed=z>=6 && imp>0.35;
    if(detailed){
      ctx.globalAlpha=a;
      ctx.fillStyle=col+'22'; ctx.strokeStyle=col; ctx.lineWidth=1+imp;
      roundRect(x-r,y-r,r*2,r*2,3); ctx.fill(); ctx.stroke();
      ctx.globalAlpha=1;
      ctx.fillStyle=col; ctx.font=`${Math.round(7+imp*4)}px ui-monospace,monospace`;
      ctx.textAlign='center'; ctx.textBaseline='middle';
      ctx.fillText(T_GLYPH[o.cat]||'•',x,y+.5);
      // «жар» — маленький бейдж кількості для гарячих цілей
      if(o.hits>=10){
        ctx.font='8px ui-monospace,monospace'; ctx.fillStyle='#ffd23f';
        ctx.fillText(o.hits,x,y-r-6);
      }
      ctx.textAlign='left'; ctx.textBaseline='alphabetic';
    } else {
      ctx.fillStyle=col; ctx.globalAlpha=a;
      const s=Math.max(3,r);
      ctx.fillRect(x-s/2,y-s/2,s,s); ctx.globalAlpha=1;
    }
  }
  const btn=document.getElementById('layToggle');
  let label=`🎯 Обʼєкти · ${shown}`;
  if(hidden) label+=` (+${hidden} наблизь)`;      // ярус прихований зумом
  btn.textContent=label;
}
function roundRect(x,y,w,h,r){
  ctx.beginPath(); ctx.moveTo(x+r,y);
  ctx.arcTo(x+w,y,x+w,y+h,r); ctx.arcTo(x+w,y+h,x,y+h,r);
  ctx.arcTo(x,y+h,x,y,r); ctx.arcTo(x,y,x+w,y,r); ctx.closePath();
}
// клік по обʼєкту-цілі — власний hit-test, бо це вже не Leaflet-маркер
function nearestTarget(latlng){
  if(!tActive.size) return null;
  const c=map.latLngToContainerPoint(latlng), b=map.getBounds(), z=map.getZoom();
  let best=null,bd=11;
  for(const o of TARGETS.objects){
    if(!tActive.has(o.cat) || z<(TIER_ZOOM[o.tier||3]||0)) continue;
    if(!b.contains([o.lat,o.lon])) continue;
    const p=map.latLngToContainerPoint([o.lat,o.lon]);
    const d=Math.hypot(p.x-c.x,p.y-c.y);
    if(d<bd){bd=d;best=o;}
  }
  return best;
}

const _panel=document.getElementById('layPanel');
function tPanel(msg){
  _panel.innerHTML='<div class=hint>Цілі у видимій області:</div>'+
    (msg?`<div class=hint>${esc(msg)}</div>`
       : Object.keys(T_LABEL).filter(k=>tCounts[k]).map(k=>
         `<label><input type=checkbox data-cat="${k}">`+
         `<span class=dot style="background:${TARGETS.colors[k]}22;`+
         `border:1px solid ${TARGETS.colors[k]};color:${TARGETS.colors[k]};`+
         `width:15px;height:15px;border-radius:3px;font-size:9px;line-height:14px;`+
         `text-align:center">${T_GLYPH[k]||''}</span>`+
         `${T_LABEL[k]}<span class=cnt>${tCounts[k]}</span></label>`).join('')
    ||'<div class=hint>шар цілей недоступний</div>');
  _panel.querySelectorAll('input').forEach(cb=>cb.onchange=()=>{
    cb.checked?tActive.add(cb.dataset.cat):tActive.delete(cb.dataset.cat);
    draw();
  });
}
tPanel('завантаження…');
document.getElementById('layToggle').onclick=()=>{_panel.hidden=!_panel.hidden;};

// Спільні файли тягнемо, а не вшиваємо в кожну добу. Два кандидати: у зібраному
// сайті сторінка лежить у site/raids/, поряд із site/<файл>; при ручному запуску
// з кореня репозиторію — поряд із самим файлом. Мережа може й не дати файл —
// карта подій від цього не залежить, просто шар лишиться порожнім.
async function loadShared(name){
  for(const u of ['../'+name, name]){
    try{ const r=await fetch(u); if(r.ok) return await r.json(); }
    catch(e){/* пробуємо наступний */}
  }
  return null;
}

loadShared('targets.json').then(d=>{
  if(!d){ console.warn('targets.json не завантажено — шар цілей вимкнено');
          tPanel('targets.json недоступний'); return; }
  TARGETS=d;
  (TARGETS.objects||[]).forEach(o=>tCounts[o.cat]=(tCounts[o.cat]||0)+1);
  tPanel(); draw();
});

// Межі областей. Контури малюються завжди, заливка — лише під тривогою; поки
// файл їде, draw() бачить порожній обʼєкт і просто їх не малює.
loadShared('regions.json').then(d=>{
  if(!d){ console.warn('regions.json не завантажено — карта без меж областей'); return; }
  POLY=d; draw();
});

sync(); start();
</script></body></html>"""

# Пунктир на карті — межа підконтрольної Україні території, той самий контур,
# від якого рахується «глибина» (territory.depth_km). Раніше тут була ламана з
# восьми точок від руки, і вона ж у трьох копіях рахувала глибину.
UA_RINGS = [[[la, lo] for la, lo in ring]
            for _, _, _, _, ring in __import__("tgmine.territory", fromlist=["x"])._ua_rings()]


def track_warning(null, n_tracks) -> str:
    """Попередження про треки — з числами ЦІЄЇ доби, а не вшитими.

    Раніше на всіх 30 сторінках стояло одне: «12 треків проти 5.4 очікуваних
    (z=+4.55)». Це результат 2026-07-17 — найкращої ночі в наборі; у липні
    2026 медіана z по 31 ночі була 0.00. Тобто типової ночі сторінка
    стверджувала значущість, якої в її даних не було. Тому текст нижче
    береться з нуль-тесту СВОЄЇ ночі й має три градації, а не одне число.
    """
    base = ("Треки — статистичні гіпотези, не виміряні траєкторії: ланцюжки "
            "окремих повідомлень, поєднані за швидкістю й курсом. ")
    if not null:
        return base + ("Цієї доби фіксацій замало, щоб перевірити їх на "
                       "випадковість.")
    obs, mean, z = null["observed"], null["mean"], null["z"]
    got = (f"Цієї доби їх {obs}, а перемішування часових міток дає в середньому "
           f"{mean:.1f} (z={z:+.2f}). ")
    if z >= 2:
        verdict = ("Це помітно більше за випадковість, але кожен окремий трек "
                   "усе одно лишається припущенням.")
    elif z > 0:
        verdict = ("Різниця в межах випадкового розкиду — цієї доби треки варто "
                   "читати як ілюстрацію, не як доказ руху.")
    else:
        verdict = ("Це не більше, ніж дає випадковість: цієї доби треки не є "
                   "свідченням руху взагалі.")
    return base + got + verdict


def jsdump(obj) -> str:
    """JSON для вставки всередину <script>. Просто json.dumps НЕБЕЗПЕЧНИЙ.

    Текст постів і назви обʼєктів з OSM пишуть сторонні люди. Python не екранує
    `/`, тому пост із рядком `</script>` закриває тег — усе після нього браузер
    читає як розмітку, і чужий <script> виконується на нашому домені.
    Перевірено PoC: пост із таким текстом виставляв window.PWNED.

    `<`, `>`, `&` у виводі json.dumps можуть стояти тільки всередині рядкових
    літералів (структурні символи JSON — це {}[]",:), тому заміняти їх глобально
    безпечно: \\uXXXX — валідний JSON і парситься назад у той самий символ.
    U+2028/U+2029 — легальні в JSON, але в JS це розриви рядка.
    """
    s = json.dumps(obj, ensure_ascii=False)
    return (s.replace("<", "\\u003c").replace(">", "\\u003e")
             .replace("&", "\\u0026")
             .replace("\u2028", "\\u2028").replace("\u2029", "\\u2029"))


def render(tpl: str, subs: dict) -> str:
    """Одним проходом. Послідовні .replace() підставляли дані, а потім шукали
    наступний плейсхолдер уже РАЗОМ із підставленим — пост із текстом
    `__TARGETS__` ламав сторінку. Один прохід цього не допускає.
    """
    rx = re.compile("|".join(re.escape(k) for k in sorted(subs, key=len, reverse=True)))
    return rx.sub(lambda m: subs[m.group(0)], tpl)


def main(src="raid_2026-07-17.json"):
    raid = json.load(open(src, encoding="utf-8"))
    ev = [e for e in raid["events"] if e.get("lat")]
    trk = raid.get("tracks", [])
    # Час ОСТАННЬОЇ ПОДІЇ доби, а не час збірки. Різниця не косметична:
    # раніше тут стояв datetime.now(), тож кожна перезбірка давала інший байт,
    # і карта завершеної ночі перезаливалась на хостинг щогодини — 800 КБ на
    # дві карти за прогін, при тому що вміст не мінявся. Тепер карта минулої
    # доби байт-у-байт стала, а сьогоднішня оновлюється, бо в ній справді
    # зʼявляються події.
    #
    # Для читача так теж чесніше: «збірка 19.07 19:41» на карті вчорашньої ночі
    # не означала нічого, а час останньої події означає, доки дані доходили.
    stamps = [e["t"] for e in raid["events"] if e.get("t")]
    if stamps:
        from datetime import datetime as _dt
        build = _dt.fromisoformat(max(stamps)).strftime("%d.%m %H:%M")
    else:
        build = raid["date"]
    regs = len({e["region"] for e in ev if e["region"]})
    places = len({e["place"] for e in ev})
    sub = (f"{ev[0]['hhmm']}–{ev[-1]['hhmm']} МСК · {len(ev)} повідомлень · "
           f"{places} НП · {regs} регіонів · {len(trk)} треків")
    warn = track_warning(raid.get("null"), len(trk))
    note = ("Джерела: lpr1_treugolnik, kupolrussia, vrv_radar (дзеркала схлопнуто). "
            "Точки — центри НП зі згадок у повідомленнях, не координати апаратів і "
            "не підтверджені влучання. Час повідомлення випереджає проліт на "
            "невідому величину, тому рух комет — реконструкція, а не запис. "
            "Це дані про ПОВІДОМЛЕННЯ, не про факти.")
    # targets.json свідомо НЕ вбудовується — сторінка тягне його сама, щоб не
    # застигнути зі старим знімком і не дублювати 656 КБ у кожну добу.
    # jsdump, не json.dumps: усередині <script> сирий JSON дозволяє чужому
    # тексту закрити тег. Один прохід: дані не мають бути видимі наступним
    # підстановкам.
    html = render(TPL, {
        "__DATA__": jsdump(raid),
        "__UA_RINGS__": jsdump(UA_RINGS),
        "__TITLE__": f"Доба {raid['date']}",
        "__SUB__": sub,
        "__WARN__": warn,
        "__NOTE__": note,
        "__DATE__": raid["date"],
        "__BUILD__": build,
    })
    out = Path(src).with_suffix(".html")
    out.write_text(html, encoding="utf-8")
    print(f"-> {out}  ({len(ev)} подій, {places} НП, {len(trk)} треків)")


if __name__ == "__main__":
    main(*sys.argv[1:])
