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

export async function write(st, id, map, sha, user) {
  const text = JSON.stringify(map);
  const bytes = new TextEncoder().encode(text);
  let bin = "";
  for (const b of bytes) bin += String.fromCharCode(b);
  const title = (map && map.title) || id;
  const sub = (map && map.sub) || "";
  const res = await gh(st, `/repos/${st.repo}/contents/${path(id)}`, {
    method: "PUT",
    body: JSON.stringify({
      message: `карта: ${title}${sub ? " · " + sub : ""} (${user || "редактор"})`,
      content: btoa(bin),
      branch: st.branch,
      ...(sha ? { sha } : {}),
    }),
  });
  if (res.status === 409 || res.status === 422) {
    // Файл змінився з того часу, як редактор брав його sha. Пишемо поверх
    // свіжого sha, а не мовчимо: інакше робота лишиться незбереженою.
    const cur = await read(st, id);
    if (cur && cur.sha !== sha) return write(st, id, map, cur.sha, user);
    throw new Error(`GitHub ${res.status}: ${(await res.text()).slice(0, 200)}`);
  }
  if (!res.ok) throw new Error(`GitHub ${res.status}: ${(await res.text()).slice(0, 200)}`);
  const out = await res.json();
  return { sha: out.content.sha };
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
