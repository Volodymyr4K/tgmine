// Зовнішній годинник для конвеєра tgmine.
//
// Навіщо. Подія `schedule` у GitHub Actions навмисно депріоритезована: вона
// потрапляє в чергу, яку GitHub розгрібає за залишковим принципом, і під
// навантаженням частина запусків просто відкидається. Виміряно на цьому
// репозиторії за 5 діб: крон "0 * * * *" обіцяв 24 прогони на добу, фактично
// вийшло 11.6, медіанний інтервал 121 хвилина замість 60, максимальний — 238.
//
// `workflow_dispatch` через API такої черги не має й підхоплюється одразу.
// Тому розклад живе тут, а в Actions лишається лише запобіжник на випадок,
// якщо помре цей Worker.
//
// Наслідок для сайту: сторінка «Що зараз» вважає дані несвіжими після 120
// хвилин. При медіані 121 це попередження горіло приблизно половину часу й
// привчало читача його ігнорувати. З детермінованим інтервалом поріг знову
// щось означає.

export default {
  async scheduled(event, env, ctx) {
    const url = `https://api.github.com/repos/${env.GH_REPO}` +
                `/actions/workflows/${env.GH_WORKFLOW}/dispatches`;

    const res = await fetch(url, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${env.GH_TOKEN}`,
        Accept: "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        // GitHub відповідає 403 на запити без User-Agent.
        "User-Agent": "tgmine-cron",
        "Content-Type": "application/json",
      },
      // `trigger: cron` відрізняє цей тік від ручного натискання кнопки в
      // Actions. Workflow за ним вибирає швидкий набір тестів: код між
      // годинними прогонами не змінюється, а повний набір вантажить газетир
      // на 132 МБ і додає ~30 с, тобто зайву білінгову хвилину на кожен тік.
      body: JSON.stringify({ ref: env.GH_REF, inputs: { trigger: "cron" } }),
    });

    // 204 — прийнято. Тіла у відповіді нема, тому читати його немає сенсу.
    if (res.status === 204) {
      console.log(`dispatch ok: ${env.GH_REPO} ${env.GH_WORKFLOW} @ ${env.GH_REF}`);
      return;
    }

    // Кидаємо, а не просто логуємо: інакше невдалий диспатч виглядає як
    // успішний тік крону, і зупинку конвеєра видно лише за тим, що сайт
    // перестав оновлюватись. Виняток піднімає лічильник помилок Worker.
    const body = await res.text();
    console.error(`dispatch failed ${res.status}: ${body}`);
    throw new Error(`GitHub dispatch повернув ${res.status}`);
  },
};
