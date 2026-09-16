// GET|PUT|DELETE /api/maps/<id> — одна карта. Вхід уже перевірено
// middleware: сюди доходить лише запит із чинною сесією.
import { store, read, write, remove, okId, noStore, noConfig } from "../_store.js";

const bad = () => noStore({ error: "недопустимий ідентифікатор карти" }, 400);

export async function onRequestGet({ env, params }) {
  const st = store(env);
  if (!st) return noConfig();
  if (!okId(params.id)) return bad();
  try {
    const got = await read(st, params.id);
    return got ? noStore(got) : noStore({ error: "нема такої карти" }, 404);
  } catch (e) {
    return noStore({ error: String(e.message || e) }, 502);
  }
}

export async function onRequestPut({ request, env, params, data }) {
  const st = store(env);
  if (!st) return noConfig();
  if (!okId(params.id)) return bad();
  let body;
  try { body = await request.json(); } catch { return noStore({ error: "це не JSON" }, 400); }
  if (!body || typeof body.map !== "object" || !body.map || !Array.isArray(body.map.objs))
    return noStore({ error: "у тілі нема карти" }, 400);
  try {
    const out = await write(st, params.id, body.map, body.sha || "", data && data.user);
    return noStore({ id: params.id, sha: out.sha, at: new Date().toISOString() });
  } catch (e) {
    return noStore({ error: String(e.message || e) }, 502);
  }
}

export async function onRequestDelete({ request, env, params, data }) {
  const st = store(env);
  if (!st) return noConfig();
  if (!okId(params.id)) return bad();
  const sha = new URL(request.url).searchParams.get("sha") || "";
  try {
    const gone = await remove(st, params.id, sha, data && data.user);
    return gone ? noStore({ id: params.id, deleted: true })
                : noStore({ error: "нема такої карти" }, 404);
  } catch (e) {
    return noStore({ error: String(e.message || e) }, 502);
  }
}
