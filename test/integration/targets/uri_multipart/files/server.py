#!/usr/bin/env python
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)
from __future__ import absolute_import, division, print_function
__metaclass__ = type

import cgi
import hashlib
import json
import sys

try:
    from http.server import BaseHTTPRequestHandler, HTTPServer
except ImportError:
    from BaseHTTPServer import BaseHTTPRequestHandler, HTTPServer


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        form = cgi.FieldStorage(fp=self.rfile, headers=self.headers, environ={
            'REQUEST_METHOD': 'POST', 'CONTENT_TYPE': self.headers['Content-Type'],
            'CONTENT_LENGTH': self.headers['Content-Length'],
        })
        fields = {}
        for name in form:
            field = form[name]
            content = field.file.read()
            if not isinstance(content, bytes):
                content = content.encode('utf-8')
            fields[name] = {'filename': field.filename, 'mime_type': field.type,
                            'sha256': hashlib.sha256(content).hexdigest()}
        body = json.dumps(fields).encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)


HTTPServer(('127.0.0.1', int(sys.argv[1])), Handler).serve_forever()
