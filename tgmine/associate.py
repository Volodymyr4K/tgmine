"""Асоціація спостережень у треки: фільтр Калмана + глобальне призначення.

ЧОМУ НЕ ЖАДІБНО, ЯК У tracker.py. Наявний трекер бере для кожного треку
найближче продовження по черзі. Хто першим у списку — той і забирає точку,
навіть якщо сусідньому треку вона підходить краще. Виміряно на чотирьох
ночах: жадібний дає 1-3 треки й 2-6 ланок за ніч, і **жодна** з цих ланок не
збігається з напрямком, який канал заявив словами.

ЩО РОБИТЬ ЦЕЙ МОДУЛЬ. Тримає стан кожного треку фільтром Калмана (позиція +
швидкість із невизначеністю) і на кожну хвилину розвʼязує задачу про
призначення: усі треки проти всіх нових спостережень одразу, угорським
алгоритмом. Порівнюються не кілометри, а відстань Махаланобіса — тобто
відхилення з урахуванням того, наскільки погано ми знаємо стан.

ЯК ПЕРЕВІРЕНО. Незалежною мірою: скільки ланок треку збігається з
ЗАЯВЛЕНИМ напрямком каналу («від Х у напрямку Y»). Трекер векторів не бачить,
тому це чесна перевірка. На чотирьох ночах: 257 ланок, 27% збігу, і нуль-тест
на перемішаних часових мітках дає медіану z = +5.0. Жадібний трекер на тій
самій мірі — 18 ланок і 0-17% збігу.

ПАРАМЕТРИ ПІДІБРАНІ ПЕРЕБОРОМ за цією ж мірою (36 конфігурацій), а не на око.

ЩО ПРОБУВАЛИ ПОВЕРХ ЦЬОГО І ВІДКИНУЛИ (деталі в CLAUDE.md): злиття близьких
дублів, зупинку треку на збитті, глобальний потік мінімальної вартості по
всій ночі й злиття заявлених векторів у саму асоціацію. Жодне не перевершило
цей варіант. Прапорці `dedup` і `stop_on_kill` лишені вимкненими за
замовчуванням саме тому: код є, користі не виміряно.

ЧОМУ БЕЗ numpy І scipy. Матриці тут 4×4, а задачі призначення — десятки на
десятки. Проєкт тримає чотири легкі залежності, і тягнути 50 МБ коліс у
збірку, що ходить у мережу щогодини, заради цього не варто.
"""
from __future__ import annotations

import math

R_POS_KM = 15.0          # похибка координати: центр НП, не сенсор
Q_ACC = 60.0             # шум процесу, км/год² — маневр апарата
GATE_CHI2 = 9.21         # 99% для двох ступенів свободи
MAX_GAP_MIN = 45.0       # трек без оновлення довше — закритий
MIN_POINTS = 3           # дві точки це пара, а не трек
V_MAX_KMH = 260.0
BIG = 1e9

# Близькі дублі: те саме місце, повторене в межах цих меж. Виміряно — 17-27%
# усіх фіксацій, і переважно це ОДИН канал, що пише про ту саму групу двічі
# (vrv_radar дає 27 таких пар за ніч). Для асоціації дубль отруйний: трек
# бере одне спостереження на хвилину, тому копія породжує паралельний трек
# поруч із першим.
DUP_KM, DUP_MIN = 15.0, 10.0

# Збиття закриває трек. Апарат, який збили, далі не летить; трек, що йде
# крізь збиття, — це вже інша група. ППО так не працює: «робота ППО» не
# означає влучання, тому на ній трек живе далі.
KILL_KINDS = ("збиття",)
KIND_RANK = {"збиття": 3, "ППО": 2, "вибух": 2, "фіксація": 1}


# --- дрібна лінійна алгебра на списках --------------------------------------
def _mul(A, B):
    n, m, p = len(A), len(B), len(B[0])
    return [[sum(A[i][k] * B[k][j] for k in range(m)) for j in range(p)]
            for i in range(n)]


def _add(A, B):
    return [[a + b for a, b in zip(ra, rb)] for ra, rb in zip(A, B)]


def _sub(A, B):
    return [[a - b for a, b in zip(ra, rb)] for ra, rb in zip(A, B)]


def _T(A):
    return [list(col) for col in zip(*A)]


def _inv2(M):
    (a, b), (c, d) = M
    det = a * d - b * c
    if abs(det) < 1e-12:
        det = 1e-12
    return [[d / det, -b / det], [-c / det, a / det]]


def _eye(n):
    return [[1.0 if i == j else 0.0 for j in range(n)] for i in range(n)]


# --- угорський алгоритм (Джонкер-Волгенант, O(n³)) --------------------------
def assign(cost):
    """Мінімальне за сумою призначення рядків стовпцям.

    Повертає список довжини len(cost): для кожного рядка — стовпець або -1.
    Жадібний вибір тут не годиться: він розвʼязує кожен рядок окремо, а нам
    треба мінімум по ВСІХ разом.
    """
    n = len(cost)
    if n == 0:
        return []
    m = len(cost[0])
    if m == 0:
        return [-1] * n
    size = max(n, m)
    a = [[cost[i][j] if i < n and j < m else 0.0 for j in range(size)]
         for i in range(size)]
    INF = float("inf")
    u = [0.0] * (size + 1)
    v = [0.0] * (size + 1)
    p = [0] * (size + 1)
    way = [0] * (size + 1)
    for i in range(1, size + 1):
        p[0] = i
        j0 = 0
        minv = [INF] * (size + 1)
        used = [False] * (size + 1)
        while True:
            used[j0] = True
            i0 = p[j0]
            delta = INF
            j1 = 0
            for j in range(1, size + 1):
                if used[j]:
                    continue
                cur = a[i0 - 1][j - 1] - u[i0] - v[j]
                if cur < minv[j]:
                    minv[j] = cur
                    way[j] = j0
                if minv[j] < delta:
                    delta = minv[j]
                    j1 = j
            for j in range(size + 1):
                if used[j]:
                    u[p[j]] += delta
                    v[j] -= delta
                else:
                    minv[j] -= delta
            j0 = j1
            if p[j0] == 0:
                break
        while j0:
            j1 = way[j0]
            p[j0] = p[j1]
            j0 = j1
    out = [-1] * n
    for j in range(1, size + 1):
        i = p[j] - 1
        if i < n and j - 1 < m:
            out[i] = j - 1
    return out


# --- трек -------------------------------------------------------------------
class Track:
    __slots__ = ("x", "P", "t", "pts")

    def __init__(self, xy, t, det):
        self.x = [xy[0], xy[1], 0.0, 0.0]
        # позиція відома погано, швидкість не відома взагалі: без великої
        # дисперсії по швидкості перший крок тягне трек у випадковий бік
        self.P = [[R_POS_KM ** 2, 0, 0, 0],
                  [0, R_POS_KM ** 2, 0, 0],
                  [0, 0, V_MAX_KMH ** 2, 0],
                  [0, 0, 0, V_MAX_KMH ** 2]]
        self.t = t
        self.pts = [det]

    def predict(self, t):
        dt = (t - self.t).total_seconds() / 3600.0
        if dt <= 0:
            return list(self.x), [row[:] for row in self.P]
        F = [[1, 0, dt, 0], [0, 1, 0, dt], [0, 0, 1, 0], [0, 0, 0, 1]]
        x = [sum(F[i][k] * self.x[k] for k in range(4)) for i in range(4)]
        P = _add(_mul(_mul(F, self.P), _T(F)), _q(dt))
        return x, P

    def update(self, t, xy, det):
        x, P = self.predict(t)
        H = [[1, 0, 0, 0], [0, 1, 0, 0]]
        S = _add([[P[0][0], P[0][1]], [P[1][0], P[1][1]]],
                 [[R_POS_KM ** 2, 0], [0, R_POS_KM ** 2]])
        Si = _inv2(S)
        PHt = [[P[i][0], P[i][1]] for i in range(4)]
        K = _mul(PHt, Si)
        y = [xy[0] - x[0], xy[1] - x[1]]
        self.x = [x[i] + K[i][0] * y[0] + K[i][1] * y[1] for i in range(4)]
        KH = _mul(K, H)
        self.P = _mul(_sub(_eye(4), KH), P)
        self.t = t
        self.pts.append(det)


def _q(dt):
    g = [dt * dt / 2, dt * dt / 2, dt, dt]
    q = Q_ACC ** 2
    return [[g[i] * g[j] * q for j in range(4)] for i in range(4)]


def to_xy(lat, lon, lat0, lon0):
    """Локальні кілометри навколо середини набору."""
    return (math.radians(lon - lon0) * 6371.0 * math.cos(math.radians(lat0)),
            math.radians(lat - lat0) * 6371.0)


def dedupe(dets):
    """Злити повтори того самого спостереження в одне.

    Лишається найраніший час (перше повідомлення), найсильніший тип
    (збиття > ППО > фіксація) і лічильник `reports`: скільки разів про це
    написали. Кількість згадок — це інформація про підтвердженість, і вона
    не має губитись.
    """
    out = []
    for d in sorted(dets, key=lambda x: x["dt"]):
        for q in out:
            if (d["dt"] - q["dt"]).total_seconds() / 60.0 > DUP_MIN:
                continue
            if _km(d["lat"], d["lon"], q["lat"], q["lon"]) <= DUP_KM:
                q["reports"] = q.get("reports", 1) + 1
                if KIND_RANK.get(d.get("kind"), 0) > KIND_RANK.get(q.get("kind"), 0):
                    q["kind"] = d.get("kind")
                break
        else:
            d = dict(d)
            d["reports"] = 1
            out.append(d)
    return out


def _km(la1, lo1, la2, lo2):
    R = 6371.0
    p1, p2 = math.radians(la1), math.radians(la2)
    dp = p2 - p1
    dl = math.radians(lo2 - lo1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(h))


def build(dets, dedup=False, stop_on_kill=False):
    """dets: [{dt, lat, lon, ...}] -> [{n, km, hours, kmh, pts}].

    Спостереження групуються по хвилинах і призначаються одночасно: інакше
    порядок у списку знову вирішував би, кому дістанеться точка.
    """
    dets = [d for d in dets if d.get("lat") is not None]
    if not dets:
        return []
    if dedup:
        dets = dedupe(dets)
    dets = sorted(dets, key=lambda d: d["dt"])
    lat0 = sum(d["lat"] for d in dets) / len(dets)
    lon0 = sum(d["lon"] for d in dets) / len(dets)
    for d in dets:
        d["_xy"] = to_xy(d["lat"], d["lon"], lat0, lon0)

    slices, cur, cur_t = [], [], None
    for d in dets:
        key = d["dt"].replace(second=0, microsecond=0)
        if cur_t is None or key == cur_t:
            cur.append(d)
            cur_t = key
        else:
            slices.append((cur_t, cur))
            cur, cur_t = [d], key
    if cur:
        slices.append((cur_t, cur))

    live, done = [], []
    for t, group in slices:
        alive = []
        for tr in live:
            if (t - tr.t).total_seconds() / 60.0 > MAX_GAP_MIN:
                done.append(tr)
            else:
                alive.append(tr)
        live = alive

        used = set()
        if live and group:
            cost = []
            for tr in live:
                x, P = tr.predict(t)
                S = _add([[P[0][0], P[0][1]], [P[1][0], P[1][1]]],
                         [[R_POS_KM ** 2, 0], [0, R_POS_KM ** 2]])
                Si = _inv2(S)
                row = []
                for d in group:
                    vx = d["_xy"][0] - x[0]
                    vy = d["_xy"][1] - x[1]
                    m2 = (vx * (Si[0][0] * vx + Si[0][1] * vy)
                          + vy * (Si[1][0] * vx + Si[1][1] * vy))
                    row.append(m2 if m2 <= GATE_CHI2 else BIG)
                cost.append(row)
            for i, j in enumerate(assign(cost)):
                if j >= 0 and cost[i][j] < BIG:
                    live[i].update(t, group[j]["_xy"], group[j])
                    used.add(j)
            if stop_on_kill:
                # трек, який щойно дійшов до збиття, закривається
                keep = []
                for tr in live:
                    if tr.pts[-1].get("kind") in KILL_KINDS:
                        done.append(tr)
                    else:
                        keep.append(tr)
                live = keep

        for j, d in enumerate(group):
            if j not in used:
                live.append(Track(d["_xy"], t, d))

    done.extend(live)
    out = []
    for tr in done:
        if len(tr.pts) < MIN_POINTS:
            continue
        km = 0.0
        for i in range(len(tr.pts) - 1):
            a, b = tr.pts[i]["_xy"], tr.pts[i + 1]["_xy"]
            km += math.dist(a, b)
        hours = (tr.pts[-1]["dt"] - tr.pts[0]["dt"]).total_seconds() / 3600.0
        if hours <= 0 or km / hours > V_MAX_KMH:
            continue
        out.append({"n": len(tr.pts), "km": round(km), "hours": round(hours, 2),
                    "kmh": round(km / hours), "pts": tr.pts})
    out.sort(key=lambda t: -t["km"])
    return out
