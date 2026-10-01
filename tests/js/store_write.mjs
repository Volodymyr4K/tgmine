// Правило запису карт на сервер (functions/api/_store.js: write) проти
// підробленого GitHub Contents API. Кожен випадок — із затирань, знайдених в
// історії mapper/maps 1 жовтня 2026. Запуск: node tests/js/store_write.mjs
import assert from "node:assert/strict";
import { write, read } from "../../functions/api/_store.js";

const st = { token: "t", repo: "o/r", branch: "main" };
let repo, race, calls;

const b64 = (o) => Buffer.from(JSON.stringify(o), "utf8").toString("base64");
const json = (body, status = 200) => new Response(JSON.stringify(body), { status });
function put(file, body) {
  const sha = "sha" + (++repo.n);
  repo.files[file] = { sha, content: body.content, message: body.message };
  return json({ content: { sha } });
}
globalThis.fetch = async (url, init = {}) => {
  const u = new URL(url);
  calls.push((init.method || "GET") + " " + u.pathname);
  const mc = /\/contents\/(.+)$/.exec(u.pathname);
  if (mc) {
    const file = decodeURIComponent(mc[1]), cur = repo.files[file];
    if (!init.method || init.method === "GET")
      return cur ? json({ sha: cur.sha, content: cur.content }) : json({ message: "Not Found" }, 404);
    const body = JSON.parse(init.body);
    if (race > 0) { race--; return json({ message: "branch moved" }, 409); }
    if (!cur) return body.sha ? json({ message: "no such sha" }, 409) : put(file, body);
    if (!body.sha) return json({ message: "sha wasn't supplied" }, 422);
    if (body.sha !== cur.sha) return json({ message: "does not match" }, 409);
    return put(file, body);
  }
  if (u.pathname.endsWith("/commits")) {
    const cur = repo.files[u.searchParams.get("path")];
    return json(cur ? [{ commit: { message: cur.message, committer: { date: "2026-10-01T06:42:00Z" } } }] : []);
  }
  throw new Error("несподіваний запит " + url);
};

const F = "mapper/maps/x.json";
const mapOf = (n, sub = "ніч на 1 жовтня 2026") =>
  ({ title: "Нічний наліт", sub, objs: Array.from({ length: n }, (_, i) => ({ kind: "route", i })) });
function reset(file) {
  repo = { n: 0, files: {} }; race = 0; calls = [];
  if (file) repo.files[F] = { sha: "sha0", content: b64(file.map), message: file.message };
}
const objsNow = async () => (await read(st, "x")).map.objs.length;
const finished = { map: mapOf(58), message: "карта: Нічний наліт · ніч на 1 жовтня 2026 (editor)" };

const tests = {
  async "нова карта створюється"() {
    reset();
    const out = await write(st, "x", mapOf(3), "", "editor");
    assert.ok(out.sha && !out.conflict);
    assert.equal(await objsNow(), 3);
    assert.match(repo.files[F].message, /\(editor\)$/);
  },
  async "свій sha — пишемо"() {
    reset(finished);
    const out = await write(st, "x", mapOf(60), "sha0", "editor");
    assert.ok(out.sha && !out.conflict);
    assert.equal(await objsNow(), 60);
  },
  // 26 вересня: браузер власника із завислим підзаголовком писав у карту оператора
  async "без sha чужий файл не чіпаємо"() {
    reset(finished);
    const out = await write(st, "x", mapOf(16), "", "volodymyr");
    assert.equal(out.conflict, true);
    assert.equal(out.by, "editor"); assert.equal(out.objs, 58);
    assert.equal(out.sub, "ніч на 1 жовтня 2026"); assert.equal(out.sha, "sha0");
    assert.equal(await objsNow(), 58);
  },
  // 18, 19, 20, 26, 29 вересня: наступного ранку той самий користувач
  async "без sha і свій давній файл не чіпаємо"() {
    reset(finished);
    const out = await write(st, "x", mapOf(11), "", "editor");
    assert.equal(out.conflict, true);
    assert.equal(await objsNow(), 58);
  },
  async "без sha з loose — теж ні"() {
    reset(finished);
    const out = await write(st, "x", mapOf(11), "", "editor", { loose: true });
    assert.equal(out.conflict, true);
    assert.equal(await objsNow(), 58);
  },
  // 24 вересня: двоє писали в один файл по черзі
  async "sha застарів, писав інший — конфлікт"() {
    reset(finished);
    const out = await write(st, "x", mapOf(19), "shaOLD", "volodymyr");
    assert.equal(out.conflict, true);
    assert.equal(await objsNow(), 58);
  },
  async "sha застарів, писав я сам, але без loose — конфлікт"() {
    reset(finished);
    const out = await write(st, "x", mapOf(40), "shaOLD", "editor");
    assert.equal(out.conflict, true);
    assert.equal(await objsNow(), 58);
  },
  async "sha застарів після запису на закритті вкладки (loose, той самий користувач) — пишемо"() {
    reset(finished);
    const out = await write(st, "x", mapOf(59), "shaOLD", "editor", { loose: true });
    assert.ok(out.sha && !out.conflict);
    assert.equal(await objsNow(), 59);
  },
  async "loose не відкриває чужий файл"() {
    reset(finished);
    const out = await write(st, "x", mapOf(19), "shaOLD", "volodymyr", { loose: true });
    assert.equal(out.conflict, true);
    assert.equal(await objsNow(), 58);
  },
  async "файл, відновлений з історії (без імені в коміті), нічий"() {
    reset({ map: mapOf(58), message: "карти: повернуто затерті версії з історії" });
    const out = await write(st, "x", mapOf(10), "shaOLD", "editor", { loose: true });
    assert.equal(out.conflict, true); assert.equal(out.by, "");
    assert.equal(await objsNow(), 58);
  },
  async "force (кнопка після запитання) пише поверх будь-чого"() {
    reset(finished);
    const a = await write(st, "x", mapOf(7), "", "volodymyr", { force: true });
    assert.ok(a.sha && !a.conflict);
    assert.equal(await objsNow(), 7);
    const b = await write(st, "x", mapOf(8), "shaOLD", "editor", { force: true });
    assert.ok(b.sha && !b.conflict);
    assert.equal(await objsNow(), 8);
  },
  async "409 через коміт CI при тому самому sha — повтор, а не конфлікт"() {
    reset(finished); race = 2;
    const out = await write(st, "x", mapOf(60), "sha0", "editor");
    assert.ok(out.sha && !out.conflict);
    assert.equal(await objsNow(), 60);
  },
  async "гонка за гілку при створенні — повтор"() {
    reset(); race = 1;
    const out = await write(st, "x", mapOf(3), "", "editor");
    assert.ok(out.sha && !out.conflict);
  },
  async "файл прибрали під час роботи — створюється наново"() {
    reset();
    const out = await write(st, "x", mapOf(5), "sha0", "editor");
    assert.ok(out.sha && !out.conflict);
    assert.equal(await objsNow(), 5);
  },
  async "нескінченна гонка закінчується помилкою, а не зацикленням"() {
    reset(finished); race = 99;
    await assert.rejects(() => write(st, "x", mapOf(60), "sha0", "editor"), /після пʼяти спроб/);
    assert.equal(calls.filter((c) => c.startsWith("PUT")).length, 5);
  },
  async "кирилиця в карті доходить цілою"() {
    reset();
    await write(st, "x", mapOf(1, "ніч на 1 жовтня — «їжак»"), "", "editor");
    assert.equal((await read(st, "x")).map.sub, "ніч на 1 жовтня — «їжак»");
  },
};

// Обгортка запиту: конфлікт — це 409 з описом того, що лежить на сервері,
// а не 502 і не мовчазний запис.
const { onRequestPut } = await import("../../functions/api/maps/[id].js");
const call = (body, user) => onRequestPut({
  request: new Request("https://x/api/maps/x", { method: "PUT", body: JSON.stringify(body) }),
  env: { GH_TOKEN: "t", GH_REPO: "o/r" }, params: { id: "x" }, data: { user } });
tests["PUT: конфлікт віддається як 409 з тим, що лежить на сервері"] = async () => {
  reset(finished);
  const r = await call({ map: mapOf(16) }, "volodymyr"), b = await r.json();
  assert.equal(r.status, 409);
  assert.deepEqual([b.conflict, b.by, b.objs, b.sha, b.sub], [true, "editor", 58, "sha0", "ніч на 1 жовтня 2026"]);
  assert.equal(await objsNow(), 58);
};
tests["PUT: force і loose доходять до правила лише як справжнє true"] = async () => {
  reset(finished);
  let r = await call({ map: mapOf(16), force: "так", loose: 1, sha: "shaOLD" }, "editor");
  assert.equal(r.status, 409);
  r = await call({ map: mapOf(16), force: true }, "volodymyr");
  assert.equal(r.status, 200);
  assert.ok((await r.json()).sha);
  assert.equal(await objsNow(), 16);
};

let bad = 0;
for (const [name, fn] of Object.entries(tests)) {
  try { await fn(); console.log("ok   " + name); }
  catch (e) { bad++; console.log("FAIL " + name + "\n     " + String(e.message).split("\n")[0]); }
}
console.log(`${Object.keys(tests).length - bad}/${Object.keys(tests).length}`);
process.exit(bad ? 1 : 0);
