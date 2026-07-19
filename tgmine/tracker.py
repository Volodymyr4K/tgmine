"""Асоціація окремих фіксацій у траєкторії.

Задача: з розрізнених повідомлень («о 02:14 фіксація над Х», «о 02:41 над Y»)
відновити, які з них належать одній групі БпЛА.

Метод — жадібне продовження треків із фізичними обмеженнями:
  * швидкість між сусідніми фіксаціями в межах правдоподібної для ударного БпЛА;
  * курс не змінюється різко;
  * розрив у часі обмежений, інакше зв'язуються не пов'язані події.

ВАЖЛИВО про надійність: точки — це центри НП, а не координати апарата, і час
повідомлення випереджає проліт на невідому величину. Тому треки тут —
ГІПОТЕЗИ про рух, а не виміряні траєкторії. Довгі треки з рівною швидкістю
правдоподібні; короткі й покручені — швидше збіг.
"""
from __future__ import annotations

import math

# Пороги підібрані НУЛЬ-ТЕСТОМ, не на око: перемішуємо часові мітки між
# точками (це знищує реальну динаміку) і дивимось, скільки треків алгоритм
# зліпить із шуму. Широкі пороги (60-320 км/год, 75°, 90 хв) давали 43 треки
# проти 43.7 на шумі — тобто чистий артефакт. Нижче — єдина знайдена зона,
# де сигнал перевищує шум: 12 треків проти 5.4, z=+4.55. Ще жорсткіше —
# розсипається в нуль, бо точки це центри НП, а не координати апарата.
V_MIN, V_MAX, V_NOM = 130.0, 220.0, 175.0
DT_MIN, DT_MAX = 120, 2700          # сек: 2 хв .. 45 хв
TURN_MAX = 40.0                     # градусів між сусідніми ділянками


def hav(a, b):
    R = 6371.0
    la1, lo1, la2, lo2 = map(math.radians, (*a, *b))
    h = (math.sin((la2 - la1) / 2) ** 2 +
         math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2)
    return 2 * R * math.asin(math.sqrt(h))


def bearing(a, b):
    la1, lo1, la2, lo2 = map(math.radians, (*a, *b))
    dl = lo2 - lo1
    y = math.sin(dl) * math.cos(la2)
    x = math.cos(la1) * math.sin(la2) - math.sin(la1) * math.cos(la2) * math.cos(dl)
    return (math.degrees(math.atan2(y, x)) + 360) % 360


def turn(b1, b2):
    d = abs(b1 - b2) % 360
    return min(d, 360 - d)


class Track:
    __slots__ = ("pts", "id")

    def __init__(self, pt, tid):
        self.pts = [pt]
        self.id = tid

    @property
    def last(self):
        return self.pts[-1]

    @property
    def course(self):
        if len(self.pts) < 2:
            return None
        return bearing(self.pts[-2]["xy"], self.pts[-1]["xy"])

    def cost(self, pt):
        """Ціна приєднання точки. None = неприйнятно."""
        dt = (pt["dt"] - self.last["dt"]).total_seconds()
        if not (DT_MIN <= dt <= DT_MAX):
            return None
        d = hav(self.last["xy"], pt["xy"])
        if d < 5:                       # та сама точка — не рух
            return None
        v = d / (dt / 3600.0)
        if not (V_MIN <= v <= V_MAX):
            return None
        c = self.course
        if c is not None:
            t = turn(c, bearing(self.last["xy"], pt["xy"]))
            if t > TURN_MAX:
                return None
        else:
            t = 0.0
        # менша ціна = краще: відхилення швидкості + поворот + пауза
        return (abs(v - V_NOM) / V_NOM) + (t / TURN_MAX) * 1.2 + (dt / DT_MAX) * 0.6

    def add(self, pt):
        self.pts.append(pt)

    def stats(self):
        pts = self.pts
        dist = sum(hav(pts[i]["xy"], pts[i + 1]["xy"]) for i in range(len(pts) - 1))
        dur = (pts[-1]["dt"] - pts[0]["dt"]).total_seconds() / 3600.0
        return {
            "id": self.id, "n": len(pts), "km": round(dist),
            "hours": round(dur, 2),
            "kmh": round(dist / dur) if dur > 0 else None,
            "from": pts[0]["place"], "to": pts[-1]["place"],
            "t0": pts[0]["dt"].isoformat(), "t1": pts[-1]["dt"].isoformat(),
            "course": round(bearing(pts[0]["xy"], pts[-1]["xy"])),
            "depth0": pts[0].get("depth"), "depth1": pts[-1].get("depth"),
            "points": [{"t": p["dt"].isoformat(), "hhmm": p["dt"].strftime("%H:%M"),
                        "lat": p["xy"][0], "lon": p["xy"][1], "place": p["place"],
                        "status": p.get("status"), "url": p.get("url"),
                        "depth": p.get("depth")} for p in pts],
        }


def build(detections: list[dict], min_len: int = 3, min_km: int = 80) -> list[dict]:
    """detections: [{dt, xy=(lat,lon), place, ...}] відсортовані за часом.

    Повертає треки, що пройшли поріг довжини — короткі майже завжди є збігом.
    """
    tracks: list[Track] = []
    open_: list[Track] = []
    nid = 0
    for pt in sorted(detections, key=lambda d: d["dt"]):
        # закриваємо треки, до яких уже не дотягнутись у часі
        open_ = [t for t in open_
                 if (pt["dt"] - t.last["dt"]).total_seconds() <= DT_MAX]
        best, best_c = None, None
        for t in open_:
            c = t.cost(pt)
            if c is not None and (best_c is None or c < best_c):
                best, best_c = t, c
        if best is not None:
            best.add(pt)
        else:
            nid += 1
            tr = Track(pt, nid)
            tracks.append(tr)
            open_.append(tr)
    out = []
    for t in tracks:
        if len(t.pts) < min_len:
            continue
        s = t.stats()
        if s["km"] < min_km:
            continue
        out.append(s)
    return sorted(out, key=lambda s: -s["km"])
