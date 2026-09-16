// GET /api/maps — перелік збережених карт.
import { store, list, noStore, noConfig } from "../_store.js";

export async function onRequestGet({ env }) {
  const st = store(env);
  if (!st) return noConfig();
  try {
    return noStore({ maps: await list(st) });
  } catch (e) {
    return noStore({ error: String(e.message || e) }, 502);
  }
}
