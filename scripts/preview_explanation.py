from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
class Preview(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def do_GET(self):
        self.send_response(302)
        self.send_header('Location','http://localhost:8765/')
        self.send_header('Cache-Control','no-store')
        self.end_headers()
    def do_POST(self):
        body=b'{"error":"Preview retired. Open http://localhost:8765/"}'
        self.send_response(410)
        self.send_header('Content-Type','application/json')
        self.send_header('Content-Length',str(len(body)))
        self.end_headers();self.wfile.write(body)
if __name__=='__main__':
    ThreadingHTTPServer(('127.0.0.1',8766),Preview).serve_forever()
