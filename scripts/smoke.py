"""Check a running server from the outside: one typed turn, printed.

    uv run python scripts/smoke.py http://localhost:8000 <WAXAL_TOKEN> "naka nga def"
"""

import base64
import sys

import httpx

url = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"
token = sys.argv[2] if len(sys.argv) > 2 else ""
text = sys.argv[3] if len(sys.argv) > 3 else "naka nga def"
r = httpx.post(f"{url}/api/text", json={"text": text}, headers={"x-token": token, "x-user": "smoke"}, timeout=300)
print("HTTP", r.status_code)
try:
    data = r.json()
except ValueError:
    sys.exit(f"Not JSON: {r.text[:300]}")
if r.status_code != 200:
    sys.exit(str(data))
for key in ("wolof", "english", "reply_english", "reply_wolof", "notes"):
    print(f"{key:>14}: {data.get(key)}")
audio = base64.b64decode(data["audio"]) if data.get("audio") else b""
open("smoke_reply.wav", "wb").write(audio)
print(f"{'audio':>14}: {len(audio)} bytes -> smoke_reply.wav")
