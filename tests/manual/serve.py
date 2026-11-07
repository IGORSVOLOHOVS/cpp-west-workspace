"""Serve the manual-test page and carry its API calls to the lab server (§9).

    python tests/manual/serve.py      then open http://127.0.0.1:8765/

The page holds no key. This script adds GITEA_TOKEN to every call it
forwards - from the environment, else from .claude/.env at the repository
root (R-02) - and never prints it. Standard library only.
"""

import json
import os
import re
import socket
import socketserver
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HOST, PORT = "127.0.0.1", 8765
HERE = Path(__file__).resolve().parent  # tests/manual
FORWARD = ("/api/v1/", "/api/packages/")
OWN_HOSTS = {f"127.0.0.1:{PORT}", f"localhost:{PORT}"}
ENV_LINE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$")


def git(*args):
    try:
        r = subprocess.run(["git", *args], cwd=HERE, capture_output=True, text=True)
    except FileNotFoundError:
        sys.exit("serve.py: git is not on PATH")
    if r.returncode != 0:
        sys.exit(f"serve.py: git {' '.join(args)} failed: {r.stderr.strip()}")
    return r.stdout.strip()


def lab_server():
    """(origin, 'owner/name') from the origin remote; credentials in it dropped."""
    url = urllib.parse.urlsplit(git("remote", "get-url", "origin"))
    parts = [p for p in url.path.split("/") if p]
    if url.scheme not in ("http", "https") or len(parts) < 2:
        sys.exit("serve.py: origin is not http(s)://<server>/<owner>/<repository>")
    host = url.netloc.rpartition("@")[2]
    prefix = "".join("/" + p for p in parts[:-2])  # Gitea under a sub-path
    name = parts[-1][:-4] if parts[-1].endswith(".git") else parts[-1]
    return f"{url.scheme}://{host}{prefix}", f"{parts[-2]}/{name}"


def lab_key(root):
    """GITEA_TOKEN and where it came from: the environment wins (R-02)."""
    if os.environ.get("GITEA_TOKEN"):
        return os.environ["GITEA_TOKEN"], "the environment"
    env_file = Path(root) / ".claude" / ".env"
    if env_file.is_file():
        for line in env_file.read_text(encoding="utf-8-sig").splitlines():
            m = ENV_LINE.match(line)
            if m and m.group(1) == "GITEA_TOKEN":
                return m.group(2).strip("\"'"), ".claude/.env"
    return None, None


def port_busy():
    try:
        with socket.create_connection((HOST, PORT), timeout=0.5):
            return True
    except OSError:
        return False


class Server(ThreadingHTTPServer):
    daemon_threads = True
    # On Windows, address reuse lets a second server bind a port that is
    # already in use; the tester then talks to whichever one answers.
    allow_reuse_address = False
    allow_reuse_port = False

    def server_bind(self):
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        socketserver.TCPServer.server_bind(self)
        # HTTPServer.server_bind would call socket.getfqdn() here, which hangs
        # on a lab PC without reverse DNS. The name is not needed.
        self.server_name, self.server_port = self.server_address[:2]


class Handler(SimpleHTTPRequestHandler):
    origin = repo = key = ""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(HERE), **kwargs)

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_request(self, code="-", size="-"):
        if isinstance(code, int) and code >= 400:  # quiet on success
            super().log_request(code, size)

    def foreign(self):
        """Refuse what is not this machine's page: a foreign Host (DNS
        rebinding), or an API call without the page's header (another site
        open in the same browser). Either would spend the key."""
        if self.headers.get("Host", "") not in OWN_HOSTS:
            self.send_error(403, "wrong Host")
            return True
        if self.path.startswith(FORWARD) and self.headers.get("X-Manual-Page") != "1":
            self.send_error(403, "API calls come from the page only")
            return True
        return False

    def do_GET(self):
        if self.foreign():
            return
        path = urllib.parse.urlsplit(self.path).path
        if self.path.startswith(FORWARD):
            self.forward()
        elif path == "/repo.json":
            data = json.dumps({"repo": self.repo}).encode()
            self.reply(200, "application/json", data)
        elif path == "/" or Path(self.translate_path(self.path)).is_file():
            super().do_GET()
        else:  # an issue, the pull request: the server's own pages
            self.send_response(302)
            self.send_header("Location", self.origin + self.path)
            self.send_header("Content-Length", "0")
            self.end_headers()

    def do_write(self):
        if self.foreign():
            return
        if self.path.startswith(FORWARD):
            self.forward()
        else:
            self.send_error(405, "only the API takes writes")

    do_POST = do_PUT = do_PATCH = do_DELETE = do_write

    def forward(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if self.command != "GET" else None
        req = urllib.request.Request(self.origin + self.path, body, method=self.command)
        for name in ("Content-Type", "Accept"):
            if self.headers.get(name):
                req.add_header(name, self.headers[name])
        req.add_header("Authorization", f"token {self.key}")
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                self.reply(r.status, r.headers.get("Content-Type"), r.read())
        except urllib.error.HTTPError as e:
            self.reply(e.code, e.headers.get("Content-Type"), e.read())
        except OSError as e:  # URLError too: the server is not reachable
            reason = getattr(e, "reason", e)
            text = json.dumps({"message": f"cannot reach {self.origin}: {reason}"})
            self.reply(502, "application/json", text.encode())

    def reply(self, status, content_type, data):
        self.send_response(status)
        self.send_header("Content-Type", content_type or "application/octet-stream")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def main():
    root = git("rev-parse", "--show-toplevel")
    origin, repo = lab_server()
    key, source = lab_key(root)
    if not key:
        sys.exit("serve.py: no GITEA_TOKEN in the environment or .claude/.env (R-02)")
    if port_busy():
        sys.exit(f"serve.py: port {PORT} is taken - stop the other server first")
    Handler.origin, Handler.repo, Handler.key = origin, repo, key
    try:
        server = Server((HOST, PORT), Handler)
    except OSError as e:
        sys.exit(f"serve.py: cannot bind {HOST}:{PORT}: {e}")
    print(f"Manual tests for {repo}")
    print(f"  page:   http://{HOST}:{PORT}/")
    print(f"  server: {origin}  (key from {source})")
    print("Ctrl+C stops it.", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
