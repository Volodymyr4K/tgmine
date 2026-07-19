#!/usr/bin/env python3
"""Генерує самодостатній HTML-плеєр нальоту з night_*.json.

Запуск:  python3 makemap.py night_2026-07-17_Московська.json
"""
import json
import sys
from pathlib import Path

TPL = """<!doctype html>
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
  :root{--bg:#0b0f14;--panel:#111820;--line:#1e2a36;--fg:#dbe6f0;--dim:#7c8ea0;
        --cyan:#35d0d8;--red:#ff4d5e;--amber:#ffb347;--green:#4ade80}
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--fg);
       font:14px/1.45 ui-monospace,SFMono-Regular,Menlo,monospace;height:100vh;
       display:grid;grid-template-columns:1fr 420px}
  @media(max-width:900px){body{grid-template-columns:1fr;grid-template-rows:55vh 45vh}}
  #map{width:100%;height:100%;background:#0b0f14}
  .leaflet-container{background:#0b0f14}
  aside{background:var(--panel);border-left:1px solid var(--line);overflow-y:auto;padding:16px}
  h1{font-size:15px;letter-spacing:.08em;margin:0 0 4px;text-transform:uppercase}
  .sub{color:var(--dim);font-size:12px;margin-bottom:14px}
  .clock{font-size:34px;letter-spacing:.06em;color:var(--cyan);margin:6px 0}
  .phase{color:var(--amber);font-size:12px;min-height:32px}
  .counters{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin:12px 0}
  .c{background:#0d141c;border:1px solid var(--line);border-radius:6px;padding:8px;text-align:center}
  .c b{display:block;font-size:20px}
  .c span{font-size:10px;color:var(--dim);text-transform:uppercase}
  .ctrl{display:flex;gap:6px;flex-wrap:wrap;margin:10px 0}
  button{background:#16212d;color:var(--fg);border:1px solid var(--line);
         border-radius:5px;padding:6px 12px;cursor:pointer;font:inherit;font-size:12px}
  button.on{background:var(--cyan);color:#05242a;border-color:var(--cyan)}
  input[type=range]{width:100%;accent-color:var(--cyan)}
  .feedhdr{font-size:11px;letter-spacing:.1em;color:var(--dim);margin:14px 0 8px;
           text-transform:uppercase;border-top:1px solid var(--line);padding-top:12px}
  .ev{border-left:2px solid var(--line);padding:5px 0 5px 9px;margin-bottom:7px;font-size:12px}
  .ev.pvo{border-color:var(--red)} .ev.fix{border-color:var(--cyan)}
  .ev.off{border-color:var(--green)} .ev.warn{border-color:var(--amber)}
  .ev time{color:var(--cyan);margin-right:6px}
  .ev a{color:var(--dim);text-decoration:none;font-size:10px}
  .legend{font-size:11px;color:var(--dim);margin-top:14px;border-top:1px solid var(--line);padding-top:10px}
  .legend i{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:6px}
  .note{font-size:10px;color:var(--dim);margin-top:10px;line-height:1.5}
</style></head><body>
<div id="map"></div>
<aside>
  <h1>__TITLE__</h1>
  <div class="sub">__SUB__</div>
  <div class="clock" id="clock">--:--</div>
  <div class="phase" id="phase"></div>
  <div class="counters">
    <div class="c"><b id="cFix" style="color:var(--cyan)">0</b><span>фіксації</span></div>
    <div class="c"><b id="cPvo" style="color:var(--red)">0</b><span>робота ППО</span></div>
    <div class="c"><b id="cDr" style="color:var(--amber)">0</b><span>заявл. БпЛА</span></div>
  </div>
  <div class="ctrl">
    <button id="play" class="on">Пауза</button>
    <button data-s="1" class="on">1x</button><button data-s="4">4x</button>
    <button data-s="10">10x</button><button data-s="30">30x</button>
  </div>
  <input type="range" id="scrub" min="0" max="1000" value="0">
  <div class="feedhdr">Стрічка подій</div>
  <div id="feed"></div>
  <div class="legend">
    <div><i style="background:var(--cyan)"></i>фіксація БпЛА</div>
    <div><i style="background:var(--red)"></i>робота ППО</div>
    <div><i style="background:var(--amber)"></i>тривога / небезпека</div>
    <div><i style="background:var(--green)"></i>відбій</div>
  </div>
  <div class="note">__NOTE__</div>
</aside>
<script>
const EV = __DATA__;
const geo = EV.filter(e => e.lat);
const t0 = new Date(EV[0].t), t1 = new Date(EV[EV.length-1].t);
const span = t1 - t0;

const map = L.map('map', {zoomControl:true}).setView([__CLAT__, __CLON__], 8);
L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png',
  {attribution:'&copy; OpenStreetMap, &copy; CARTO', maxZoom:14}).addTo(map);
if (geo.length) map.fitBounds(geo.map(e=>[e.lat,e.lon]), {padding:[40,40], maxZoom:8});

const COLOR = {'ППО':'#ff4d5e','фіксація':'#35d0d8','відбій':'#4ade80',
               'тривога':'#ffb347','небезпека':'#ffb347','ВКС':'#c084fc','вибух':'#ff4d5e'};
const CLS = {'ППО':'pvo','фіксація':'fix','відбій':'off','тривога':'warn','небезпека':'warn'};

let t = 0, speed = 1, playing = true, drawn = new Set(), markers = [];

function render(now){
  const cut = new Date(t0.getTime() + now);
  document.getElementById('clock').textContent =
    cut.toLocaleTimeString('uk-UA',{hour:'2-digit',minute:'2-digit',second:'2-digit'}) + ' МСК';
  let fix=0, pvo=0, dr=0, feed=[], phase='';
  EV.forEach((e,i)=>{
    if (new Date(e.t) > cut) return;
    if (e.status==='фіксація') fix++;
    if (e.status==='ППО') pvo++;
    dr += e.drones||0;
    feed.push(e);
    if (e.lat && !drawn.has(i)){
      drawn.add(i);
      const c = COLOR[e.status]||'#7c8ea0';
      const m = L.circleMarker([e.lat,e.lon],{radius:e.status==='ППО'?9:6,
        color:c, weight:2, fillColor:c, fillOpacity:.35}).addTo(map);
      m.bindPopup(`<b>${e.hhmm}</b> ${e.place||''}<br>${e.text}`);
      markers.push(m);
    }
  });
  const last = feed[feed.length-1];
  if (last) phase = `${last.place||''} — ${last.status}`;
  document.getElementById('phase').textContent = phase;
  document.getElementById('cFix').textContent = fix;
  document.getElementById('cPvo').textContent = pvo;
  document.getElementById('cDr').textContent = dr;
  document.getElementById('feed').innerHTML = feed.slice(-14).reverse().map(e=>
    `<div class="ev ${CLS[e.status]||''}"><time>${e.hhmm}</time>${e.place||''}
     <div>${e.text}</div><a href="${e.url}" target="_blank">джерело ↗</a></div>`).join('');
  document.getElementById('scrub').value = Math.round(now/span*1000);
}

function reset(){ markers.forEach(m=>map.removeLayer(m)); markers=[]; drawn=new Set(); }

let prev = performance.now();
function loop(now){
  const dt = now - prev; prev = now;
  if (playing){ t += dt * speed * 60; if (t > span){ t = span; playing=false;
    document.getElementById('play').textContent='Старт'; } render(t); }
  requestAnimationFrame(loop);
}
document.getElementById('play').onclick = e => {
  if (t >= span){ t = 0; reset(); }
  playing = !playing; e.target.textContent = playing ? 'Пауза' : 'Старт';
};
document.querySelectorAll('[data-s]').forEach(b => b.onclick = () => {
  speed = +b.dataset.s;
  document.querySelectorAll('[data-s]').forEach(x=>x.classList.remove('on'));
  b.classList.add('on');
});
document.getElementById('scrub').oninput = e => {
  const nt = e.target.value/1000*span;
  if (nt < t) reset();
  t = nt; render(t);
};
render(0); requestAnimationFrame(loop);
</script></body></html>"""


def main(src):
    ev = json.load(open(src, encoding="utf-8"))
    geo = [e for e in ev if e.get("lat")]
    clat = sum(e["lat"] for e in geo) / len(geo) if geo else 55.75
    clon = sum(e["lon"] for e in geo) / len(geo) if geo else 37.6
    name = Path(src).stem.replace("night_", "").replace("_", " · ")
    dr = sum(e.get("drones") or 0 for e in ev)
    sub = (f"{ev[0]['hhmm']}–{ev[-1]['hhmm']} МСК · {len(ev)} подій "
           f"({len(geo)} з координатами) · заявлено ≥{dr} БпЛА")
    note = ("Реконструкція за повідомленнями моніторингових Telegram-каналів "
            "(lpr1_treugolnik, kupolrussia, vrv_radar). Точки — місця згадок, "
            "не підтверджені влучання. Дзеркальні канали схлопнуто. "
            "Геокодування — GeoNames; частина топонімів може бути визначена "
            "неточно. Це дані про ПОВІДОМЛЕННЯ, не про факти.")
    html = (TPL.replace("__DATA__", json.dumps(ev, ensure_ascii=False))
               .replace("__TITLE__", name).replace("__SUB__", sub)
               .replace("__NOTE__", note)
               .replace("__CLAT__", f"{clat:.4f}").replace("__CLON__", f"{clon:.4f}"))
    out = Path(src).with_suffix(".html")
    out.write_text(html, encoding="utf-8")
    print(f"-> {out}  ({len(ev)} подій, {len(geo)} на карті)")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "night_2026-07-17_Московська.json")
