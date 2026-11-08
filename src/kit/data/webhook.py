"""OPTIONAL forward-test log: TradingView alert webhooks written to data/forward/alerts.jsonl.

By default it listens on 127.0.0.1 only — nothing outside this Mac can reach it, so by itself it
receives nothing from TradingView. TradingView only sends webhooks to ports 80/443 on a public
address, from these IPs: 52.89.214.238, 34.212.75.30, 54.218.53.128, 52.32.178.7, and requires
2-factor authentication on the account (tradingview.com/support/solutions/43000529348).
To actually receive alerts you must deliberately put a tunnel in front of it (README:
"Optional: forward-test log"). Every request must carry the secret path printed at start-up.
"""
from __future__ import annotations

import json
import secrets as pysecrets
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path


def serve(data_dir: Path, port: int = 8765, host: str = "127.0.0.1", token: str | None = None, log=print) -> None:
    token = token or pysecrets.token_urlsafe(18)
    out = Path(data_dir) / "forward" / "alerts.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)

    class H(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            if self.path.rstrip("/") != f"/{token}":
                self.send_response(404); self.end_headers(); return
            n = min(int(self.headers.get("content-length", 0)), 64_000)
            body = self.rfile.read(n).decode("utf-8", "replace")
            try:
                payload = json.loads(body)
            except json.JSONDecodeError:
                payload = {"text": body}
            rec = {"received_utc": datetime.now(timezone.utc).isoformat(), "from": self.client_address[0], "alert": payload}
            with out.open("a") as fh:
                fh.write(json.dumps(rec) + "\n")
            self.send_response(200); self.end_headers(); self.wfile.write(b"ok")

        def do_GET(self):  # noqa: N802
            self.send_response(404); self.end_headers()

        def log_message(self, *a):
            pass

    log(f"Listening on http://{host}:{port}/{token}  (only this Mac can reach it unless you add a tunnel)")
    log(f"Alerts are appended to {out}. Ctrl-C to stop.")
    HTTPServer((host, port), H).serve_forever()
