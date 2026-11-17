"""Stand-in robot for the simulator check: serves the real BEacon page (BEam's beacon/public,
path in argv[1]) plus just enough API for BEep's iPhone features. Logs photo downloads to
requests.log and saves the calendar BEep sends to calendar.json, for the workflow to check."""
import http.server
import json
import os
import sys

PUBLIC = sys.argv[1]
STATUS = {
    'name': 'BEacon', 'host': {'name': '@be/be', 'version': '13.0.9'}, 'robot': True,
    'hostname': 'Test-Jibo', 'uptimeSeconds': 4133,
    # The Android emulator reaches its host at 10.0.2.2 (BEACON_ADDRESS); the iPhone simulator at 127.0.0.1.
    'addresses': [{'iface': 'wlan0', 'address': os.environ.get('BEACON_ADDRESS', '127.0.0.1')}],
    'paths': {}, 'theme': {'name': 'None', 'live': True},
    'battery': {'level': 15, 'pluggedIn': False}
}
PEOPLE = {'members': [{'id': 'zane', 'firstName': 'Zane'}, {'id': 'robot', 'isJibo': True}]}
PHOTOS = {'available': True, 'count': 1, 'photos': [{'id': 'photo-1', 'available': True}]}


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=PUBLIC, **kwargs)

    def send_json(self, value, status=200):
        body = json.dumps(value).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split('?')[0]
        if path == '/api/photos/file':
            with open('requests.log', 'a') as log:
                log.write('photo downloaded\n')
            self.path = '/icon-512.png'
            return super().do_GET()
        if not path.startswith('/api/'):
            return super().do_GET()
        found = {'/api/status': STATUS, '/api/people': PEOPLE, '/api/photos': PHOTOS}.get(path)
        self.send_json(found if found else {'error': 'Not in the simulator check'}, 200 if found else 404)

    def do_PUT(self):
        body = self.rfile.read(int(self.headers.get('Content-Length', 0)))
        if self.path.startswith('/api/people/calendar'):
            with open('calendar.json', 'wb') as out:
                out.write(body)
            return self.send_json(PEOPLE)
        self.send_json({'error': 'Not in the simulator check'}, 404)


http.server.ThreadingHTTPServer(('0.0.0.0', 8123), Handler).serve_forever()
