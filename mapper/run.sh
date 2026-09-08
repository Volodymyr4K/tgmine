#!/bin/sh
# Редактор працює ЛИШЕ через http, не з подвійного кліку по файлу.
# Причина: рельєф — растр із диска, а браузер вважає file:// чужим джерелом
# і «отруює» полотно. Малювати таке полотно можна, а віддати PNG уже ні —
# експорт падає з Tainted canvas. Через http цього нема.
#
# Сервер віддає все з `Cache-Control: no-store`, і це не дрібниця. `labels.js`
# і `editor.html` підключені без версії в адресі, тож браузер тримав їх у
# кеші й після правки показував стару карту: оператор бачив ті самі підписи,
# які щойно прибрали, і питав «а точно задеплоїно?». Плитки підкладки лежать
# у власному кеші редактора, тож на швидкість це не впливає.
cd "$(dirname "$0")"
PORT=${1:-8765}
echo "редактор: http://localhost:$PORT/editor.html"
python3 - "$PORT" <<'PY'
import http.server, socketserver, sys

class H(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Cache-Control", "no-store, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        super().end_headers()

socketserver.TCPServer.allow_reuse_address = True
with socketserver.TCPServer(("127.0.0.1", int(sys.argv[1])), H) as s:
    s.serve_forever()
PY
