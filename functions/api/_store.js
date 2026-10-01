// Сховище готових карт. Редактор тримав роботу лише в localStorage браузера:
// один ключ, перезапис раз на 1.5 с — наступна ніч затирала попередню, а
// «очистити дані сайту» стирало все. Тепер кожна карта лягає у файл репозиторію
// через GitHub Contents API: історія версій дістається безкоштовно, архів живе
// поза Cloudflare й поза браузером, а редактор бачить свої карти з будь-якої
// машини.
//
// Секрети Pages-проєкту:
//   GH_TOKEN  — PAT із правом contents:write на репозиторій (обовʼязково)
//   GH_REPO   — «власник/репо», типово Volodymyr4K/tgmine
//   GH_BRANCH — гілка, типово main
//
// Нема токена — 503 з поясненням, а не тиха відмова: редактор показує
// «лише в браузері» й далі малює. Втратити роботу через недоступний сервер
// не можна — localStorage лишається як був.

const DIR = "mapper/maps";

export function store(env) {
  const token = env.GH_TOKEN;
  if (!token) return null;
  return {
    token,
    repo: env.GH_REPO || "Volodymyr4K/tgmine",
    branch: env.GH_BRANCH || "main",
  };
}

export const noStore = (body, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store" },
  });

export const noConfig = () =>
  noStore({ error: "сховище не налаштоване: нема секрета GH_TOKEN" }, 503);

// Ідентифікатор карти — це назва файла в репо, тож усе, що не літера латиниці,
// цифра чи дефіс, сюди не потрапляє. Без цього «../» у шляху писало б у чужі
// файли репозиторію.
export const okId = (id) => typeof id === "string" && /^[a-z0-9][a-z0-9-]{0,63}$/.test(id);

export const path = (id) => `${DIR}/${id}.json`;

async function gh(st, url, init = {}) {
  const res = await fetch(`https://api.github.com${url}`, {
    ...init,
    headers: {
      Authorization: `Bearer ${st.token}`,
      Accept: "application/vnd.github+json",
      "User-Agent": "tgmine-editor",
      "X-GitHub-Api-Version": "2022-11-28",
      ...(init.body ? { "Content-Type": "application/json" } : {}),
      ...(init.headers || {}),
    },
  });
  return res;
}

export async function list(st) {
  const res = await gh(st, `/repos/${st.repo}/contents/${DIR}?ref=${encodeURIComponent(st.branch)}`);
  if (res.status === 404) return [];          // теки ще нема — це порожній архів
  if (!res.ok) throw new Error(`GitHub ${res.status}: ${(await res.text()).slice(0, 200)}`);
  const items = await res.json();
  return (Array.isArray(items) ? items : [])
    .filter((f) => f.type === "file" && f.name.endsWith(".json"))
    .map((f) => ({ id: f.name.slice(0, -5), sha: f.sha, size: f.size }));
}

export async function read(st, id) {
  const res = await gh(st, `/repos/${st.repo}/contents/${path(id)}?ref=${encodeURIComponent(st.branch)}`);
  if (res.status === 404) return null;
  if (!res.ok) throw new Error(`GitHub ${res.status}: ${(await res.text()).slice(0, 200)}`);
  const f = await res.json();
  // base64 → текст. atob дає байти, а карта в UTF-8: без перекодування
  // кирилиця в назвах перетворюється на кашу.
  const bin = Uint8Array.from(atob(f.content.replace(/\n/g, "")), (c) => c.charCodeAt(0));
  return { sha: f.sha, map: JSON.parse(new TextDecoder().decode(bin)) };
}

// Хто й коли писав файл востаннє. Імʼя береться з повідомлення коміту —
// `write` сам кладе його в дужках у кінці («карта: … (editor)»); коміт,
// зроблений не редактором (відновлення з історії), імені не має.
export async function lastWriter(st, id) {
  const res = await gh(st, `/repos/${st.repo}/commits?path=${encodeURIComponent(path(id))}` +
    `&sha=${encodeURIComponent(st.branch)}&per_page=1`);
  if (!res.ok) return { by: "", at: "" };
  const c = (await res.json())[0];
  if (!c || !c.commit) return { by: "", at: "" };
  const m = /\(([^()]+)\)\s*$/.exec(c.commit.message || "");
  return { by: m ? m[1] : "", at: (c.commit.committer && c.commit.committer.date) || "" };
}

// Відбиток тексту карти: довжина + FNV-1a по кодових одиницях рядка. Той
// самий рахунок робить редактор (`srvHash` в editor.html) над своїм
// JSON.stringify — тут над JSON.stringify того, що лежить у файлі. Це не
// захист від зловмисника, а спосіб упізнати власний запис.
export function mapHash(map) {
  const t = JSON.stringify(map);
  let h = 0x811c9dc5;
  for (let i = 0; i < t.length; i++) { h ^= t.charCodeAt(i); h = Math.imul(h, 0x01000193); }
  return t.length + ":" + (h >>> 0).toString(16);
}

// Запис карти. Правило одне: редактор САМ пише лише у файл, який він знає —
// тобто приніс sha тієї версії, що зараз лежить у репо. Усе інше — конфлікт,
// і поверх пишеться тільки з `force` (кнопка «Зберегти» після запитання).
//
// До 1 жовтня 2026 будь-яка розбіжність sha лікувалась перечитуванням і
// записом поверх («інакше робота лишиться незбереженою»). Файл зветься за
// ніччю з підзаголовка, один на всіх, автозбереження — на кожну зміну, тож
// поверх готових карт лягало що завгодно: чужий екран із завислим
// підзаголовком, напівстерта вчорашня карта, порожня підкладка. Аудит історії
// `mapper/maps/` знайшов 12 затертих карт із 19.
//
// Що вважається «знає»:
//   sha збігається з файлом           -> пишемо;
//   sha нема, файла нема              -> створюємо;
//   sha нема, файл є                  -> конфлікт (чужа або давня карта);
//   sha не збігається                 -> конфлікт, КРІМ `loose`: редактор
//     послав запис на закритті вкладки (keepalive) і відповіді з новим sha
//     не дочекався. Він приносить відбитки того, що тоді послав; якщо у
//     файлі лежить рівно це — то його ж запис, і новіший стан його заміщає.
//     Перша версія звіряла імʼя останнього автора; одного логіна у двох
//     браузерах вистачало б, щоб затерти свіжішу роботу.
// 409 від GitHub буває й без зміни файла (гілку посунув коміт CI) — тоді
// sha той самий, і запис просто повторюється.
export async function write(st, id, map, sha, user, opt = {}) {
  const text = JSON.stringify(map);
  const bytes = new TextEncoder().encode(text);
  let bin = "";
  for (const b of bytes) bin += String.fromCharCode(b);
  const title = (map && map.title) || id;
  const sub = (map && map.sub) || "";
  let last = 0;
  for (let attempt = 0; attempt < 5; attempt++) {
    const res = await gh(st, `/repos/${st.repo}/contents/${path(id)}`, {
      method: "PUT",
      body: JSON.stringify({
        message: `карта: ${title}${sub ? " · " + sub : ""} (${user || "редактор"})`,
        content: btoa(bin),
        branch: st.branch,
        ...(sha ? { sha } : {}),
      }),
    });
    if (res.ok) {
      const out = await res.json();
      return { sha: out.content.sha };
    }
    if (res.status !== 409 && res.status !== 422 && res.status !== 404)
      throw new Error(`GitHub ${res.status}: ${(await res.text()).slice(0, 200)}`);
    last = res.status;
    const cur = await read(st, id);
    if (!cur) {
      // Файла нема. З sha — його прибрали, поки редактор працював: це та
      // сама карта того самого сеансу, створюємо наново. Без sha — гонка
      // за гілку при створенні: повтор.
      sha = "";
      continue;
    }
    if (cur.sha === sha) continue;            // файл той самий, посунулась гілка
    if (!opt.force) {
      const w = await lastWriter(st, id);
      const own = !!sha && Array.isArray(opt.loose) && opt.loose.includes(mapHash(cur.map));
      if (!own)
        return { conflict: true, sha: cur.sha, by: w.by, at: w.at,
                 objs: Array.isArray(cur.map && cur.map.objs) ? cur.map.objs.length : 0,
                 sub: (cur.map && cur.map.sub) || "" };
    }
    sha = cur.sha;
  }
  throw new Error(`GitHub ${last}: запис не вдався після пʼяти спроб`);
}

export async function remove(st, id, sha, user) {
  const cur = sha ? { sha } : await read(st, id);
  if (!cur) return false;
  const res = await gh(st, `/repos/${st.repo}/contents/${path(id)}`, {
    method: "DELETE",
    body: JSON.stringify({
      message: `карта прибрана: ${id} (${user || "редактор"})`,
      sha: cur.sha,
      branch: st.branch,
    }),
  });
  if (!res.ok) throw new Error(`GitHub ${res.status}: ${(await res.text()).slice(0, 200)}`);
  return true;
}
