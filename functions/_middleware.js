// Вхід на сайт. Весь tgmine.pages.dev — і зведення, і карти, і редактор —
// віддається лише після логіну. Middleware стоїть перед статикою Pages, тож
// жоден файл із `site/` не йде назовні без чинної сесії.
//
// Облікові записи й ключ підпису лежать у секретах Pages-проєкту, не в репо:
//   AUTH_USERS  — JSON {"логін": "sha256(пароль) hex", ...}
//   AUTH_SECRET — випадковий ключ HMAC для cookie сесії
// Нема хоч одного — сайт віддає 503, а не відкривається (fail closed).
//
// Паролі генеруються випадково (~140 біт), тому повільний хеш не потрібен:
// перебір неможливий і так, а PBKDF2 на 100k ітерацій не влазить у 10 мс CPU
// безкоштовного плану.
//
// Підпис сесії включає хеш пароля: змінив пароль у AUTH_USERS — усі старі
// сесії цього логіна мертві; прибрав логін — теж.

const COOKIE = "__Host-tgmine";
const TTL = 30 * 24 * 3600; // секунд

const enc = new TextEncoder();

const b64url = (buf) =>
  btoa(String.fromCharCode(...new Uint8Array(buf)))
    .replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");

async function sha256hex(s) {
  const d = await crypto.subtle.digest("SHA-256", enc.encode(s));
  return [...new Uint8Array(d)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

async function hmac(secret, msg) {
  const key = await crypto.subtle.importKey(
    "raw", enc.encode(secret), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  return b64url(await crypto.subtle.sign("HMAC", key, enc.encode(msg)));
}

function same(a, b) {
  const x = enc.encode(a), y = enc.encode(b);
  return x.length === y.length && crypto.subtle.timingSafeEqual(x, y);
}

function config(env) {
  try {
    const users = JSON.parse(env.AUTH_USERS || "");
    if (env.AUTH_SECRET && env.AUTH_SECRET.length >= 32 &&
        users && typeof users === "object" && Object.keys(users).length) {
      return { users, secret: env.AUTH_SECRET };
    }
  } catch {}
  return null;
}

async function makeSession(cfg, user) {
  const exp = Math.floor(Date.now() / 1000) + TTL;
  const sig = await hmac(cfg.secret, `${user}|${exp}|${cfg.users[user]}`);
  return `${encodeURIComponent(user)}.${exp}.${sig}`;
}

async function sessionUser(cfg, request) {
  const raw = (request.headers.get("Cookie") || "")
    .split(/;\s*/).find((c) => c.startsWith(COOKIE + "="));
  if (!raw) return null;
  const [u, exp, sig] = raw.slice(COOKIE.length + 1).split(".");
  if (!u || !exp || !sig) return null;
  let user;
  try { user = decodeURIComponent(u); } catch { return null; }
  if (!Object.hasOwn(cfg.users, user)) return null;
  if (!(Number(exp) > Date.now() / 1000)) return null;
  const want = await hmac(cfg.secret, `${user}|${exp}|${cfg.users[user]}`);
  return same(sig, want) ? user : null;
}

// Куди повернути після входу. Лише локальний шлях: «//evil.com» і
// «/\evil.com» браузер сприймає як інший хост.
function safeNext(v) {
  return typeof v === "string" && /^\/(?![\/\\])/.test(v) ? v : "/";
}

const esc = (s) => s.replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

function loginPage(next, error, status = 200) {
  const html = `<!doctype html>
<html lang="uk"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex">
<title>Вхід · tgmine</title>
<style>
:root{--bg:#f4f4f2;--card:#fff;--fg:#1a1a1a;--mute:#6b6b6b;--line:#d9d9d4;--acc:#1a1a1a;--accfg:#fff;--err:#b3261e}
@media (prefers-color-scheme:dark){:root{--bg:#121212;--card:#1c1c1c;--fg:#eaeaea;--mute:#9a9a9a;--line:#333;--acc:#eaeaea;--accfg:#121212;--err:#f2b8b5}}
*{box-sizing:border-box}
body{margin:0;min-height:100vh;display:grid;place-items:center;background:var(--bg);color:var(--fg);font:15px/1.4 system-ui,-apple-system,sans-serif}
form{width:min(340px,92vw);background:var(--card);border:1px solid var(--line);border-radius:10px;padding:28px 24px}
h1{margin:0 0 20px;font-size:18px;font-weight:600}
label{display:block;margin:0 0 14px;font-size:13px;color:var(--mute)}
input{display:block;width:100%;margin-top:6px;padding:10px 12px;font:inherit;color:var(--fg);background:var(--bg);border:1px solid var(--line);border-radius:6px}
input:focus{outline:2px solid var(--acc);outline-offset:-1px}
button{width:100%;margin-top:6px;padding:11px;font:inherit;font-weight:600;color:var(--accfg);background:var(--acc);border:0;border-radius:6px;cursor:pointer}
.err{margin:0 0 14px;color:var(--err);font-size:13px}
</style></head><body>
<form method="post" action="/login">
<h1>tgmine</h1>
${error ? `<p class="err">${esc(error)}</p>` : ""}
<input type="hidden" name="next" value="${esc(next)}">
<label>Логін<input name="user" autocomplete="username" autocapitalize="none" spellcheck="false" required autofocus></label>
<label>Пароль<input name="password" type="password" autocomplete="current-password" required></label>
<button>Увійти</button>
</form></body></html>`;
  return new Response(html, {
    status,
    headers: {
      "Content-Type": "text/html; charset=utf-8",
      "Cache-Control": "no-store",
      "X-Robots-Tag": "noindex",
    },
  });
}

const cookie = (value, maxAge) =>
  `${COOKIE}=${value}; Path=/; Max-Age=${maxAge}; HttpOnly; Secure; SameSite=Lax`;

export async function onRequest(context) {
  const { request, env } = context;
  const url = new URL(request.url);

  const cfg = config(env);
  if (!cfg) {
    return new Response("Вхід не налаштовано: нема AUTH_USERS або AUTH_SECRET.", {
      status: 503, headers: { "Content-Type": "text/plain; charset=utf-8", "Cache-Control": "no-store" },
    });
  }

  if (url.pathname === "/logout") {
    return new Response(null, {
      status: 303, headers: { Location: "/login", "Set-Cookie": cookie("", 0), "Cache-Control": "no-store" },
    });
  }

  if (url.pathname === "/login") {
    if (request.method === "POST") {
      const form = await request.formData();
      const user = String(form.get("user") || "").trim().toLowerCase();
      const next = safeNext(form.get("next"));
      const hash = await sha256hex(String(form.get("password") || ""));
      // Порівнюємо навіть для неіснуючого логіна — щоб час відповіді не
      // підказував, які логіни є.
      const known = Object.hasOwn(cfg.users, user);
      const ok = same(hash, known ? String(cfg.users[user]) : "0".repeat(64)) && known;
      if (!ok) return loginPage(next, "Невірний логін або пароль.", 401);
      return new Response(null, {
        status: 303,
        headers: {
          Location: next,
          "Set-Cookie": cookie(await makeSession(cfg, user), TTL),
          "Cache-Control": "no-store",
        },
      });
    }
    if (await sessionUser(cfg, request)) {
      return Response.redirect(new URL(safeNext(url.searchParams.get("next")), url).toString(), 303);
    }
    return loginPage(safeNext(url.searchParams.get("next")), "");
  }

  const user = await sessionUser(cfg, request);
  if (!user) {
    // Навігацію — на форму входу; fetch/XHR з редактора — просто 401, щоб
    // скрипт не отримав HTML форми замість JSON.
    const navigate = request.method === "GET" &&
      (request.headers.get("Sec-Fetch-Mode") === "navigate" ||
       (request.headers.get("Accept") || "").includes("text/html"));
    if (navigate) {
      const next = url.pathname + url.search;
      return new Response(null, {
        status: 302,
        headers: { Location: `/login?next=${encodeURIComponent(next)}`, "Cache-Control": "no-store" },
      });
    }
    return new Response("Потрібен вхід.", {
      status: 401, headers: { "Content-Type": "text/plain; charset=utf-8", "Cache-Control": "no-store" },
    });
  }

  const res = await context.next();
  // `_headers` ставить `public` на JS/CSS редактора. За логіном це має бути
  // `private`: спільні кеші не повинні тримати закриті файли.
  const cc = res.headers.get("Cache-Control");
  if (cc && /\bpublic\b/.test(cc)) {
    const out = new Response(res.body, res);
    out.headers.set("Cache-Control", cc.replace(/\bpublic\b/, "private"));
    return out;
  }
  return res;
}
