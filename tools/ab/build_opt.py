"""Збирач із вимикачами для ізольованих замірів: NO_LAUNCH=1, NO_SEAT=1."""
import os, runpy, sys
sys.path.insert(0, '.')
from tgmine import store as ST, geocode as GC
if os.environ.get('NO_SEAT'):
    GC.Gazetteer._seat_over_region = staticmethod(lambda q, best, pool: best)
if os.environ.get('NO_LAUNCH'):
    ST.launch_origin = lambda p: None
    _orig = ST.Store._event
    def _event(self, p, cfg):
        ev = _orig(self, p, cfg)
        ev['scope'] = 'точка' if ev['kind'] in ST.POINT_KINDS else 'область'
        return ev
    ST.Store._event = _event
sys.argv = ['build_into.py', sys.argv[1]]
runpy.run_path(os.path.join(os.path.dirname(__file__), 'build_into.py'), run_name='__main__')
