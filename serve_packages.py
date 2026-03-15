"""Simple HTTP server to serve packages and prerequisites for remote targets."""
import http.server
import os

PORT = 9090
DIRECTORY = os.path.join(os.path.dirname(__file__), "orchestrator")

os.chdir(DIRECTORY)
handler = http.server.SimpleHTTPServer = http.server.SimpleHTTPRequestHandler
print(f"Serving {DIRECTORY} on http://0.0.0.0:{PORT}")
print(f"  Packages:      http://10.0.0.11:{PORT}/artifacts/packages/")
print(f"  Prerequisites: http://10.0.0.11:{PORT}/prerequisites/")
http.server.HTTPServer(("0.0.0.0", PORT), handler).serve_forever()
