#!/usr/bin/env python3
"""Minimal API for Akme Alpha regime indicator.
Deploy to Render free tier. Cold-start downloads DB from GitHub Release.
"""
import json
import sqlite3
import urllib.request
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler

DB_PATH = Path(__file__).parent.parent / "akme_alpha.db"
RELEASE_URL = "https://github.com/mcdawgzy/akme-alpha/releases/download/v1.0.0/akme_alpha.db"


def download_db():
    """Download DB from GitHub Release on cold-start."""
    if not DB_PATH.exists():
        print("Downloading database from GitHub Release...")
        urllib.request.urlretrieve(RELEASE_URL, str(DB_PATH))
        print("DB downloaded.")


def get_regime_data(date: str = None):
    """Fetch regime data from the database."""
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    if date:
        cur.execute("SELECT * FROM regime_daily WHERE date = ?", (date,))
    else:
        cur.execute("SELECT * FROM regime_daily ORDER BY date DESC LIMIT 1")

    row = cur.fetchone()
    conn.close()

    if row:
        return dict(row)
    return None


class APIHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/api/regime" or self.path == "/api/regime/latest":
            data = get_regime_data()
            if data:
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(json.dumps(data).encode())
            else:
                self.send_response(503)
                self.end_headers()
        else:
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"Akme Alpha API")

    def log_message(self, format, *args):
        pass  # Silent in Render


if __name__ == "__main__":
    download_db()
    server = HTTPServer(("0.0.0.0", 5000), APIHandler)
    print("API running on port 5000")
    server.serve_forever()
