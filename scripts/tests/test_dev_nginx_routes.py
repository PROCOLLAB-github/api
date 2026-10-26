"""Exercise the checked-in server config with real Nginx, without Django/DB."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import shutil
import socket
import ssl
import subprocess
import sys
from tempfile import TemporaryDirectory
from threading import Thread
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from check_dev_routes import check_routes, request  # noqa: E402


class Backend(BaseHTTPRequestHandler):
    def respond(self, status):
        body = json.dumps({"backend_method": self.command, "backend_path": self.path}).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        protected = {"/auth/users/current/", "/solution-invitations/", "/solution-form-templates/"}
        self.respond(401 if self.path.partition("?")[0] in protected else 404)

    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length", 0)))
        self.respond(400)

    def log_message(self, *args):
        pass


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@unittest.skipUnless(shutil.which("nginx"), "Nginx is required; exercised in DEV Nginx routing CI")
class DevRoutingTests(unittest.TestCase):
    def test_spa_reads_and_api_requests(self):
        repo = Path(__file__).resolve().parents[2]
        with TemporaryDirectory(prefix="dev-nginx-routing-") as directory:
            root = Path(directory)
            (root / "logs").mkdir()
            temp_paths = "".join(
                f"{name}_temp_path {root}/{name};\n"
                for name in ("client_body", "proxy", "fastcgi", "uwsgi", "scgi")
            )
            (root / "index.html").write_text("<!doctype html><app-root></app-root>")
            (root / "asset.js").write_text("window.fixture = true;")
            subprocess.run([
                "openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
                "-subj", "/CN=localhost", "-keyout", str(root / "key.pem"), "-out", str(root / "cert.pem"),
            ], check=True, capture_output=True)
            backend = ThreadingHTTPServer(("127.0.0.1", 0), Backend)
            Thread(target=backend.serve_forever, daemon=True).start()
            self.addCleanup(backend.server_close)
            self.addCleanup(backend.shutdown)
            http_port, https_port = free_port(), free_port()
            proxy = (repo / "deploy/nginx/host/includes/proxy_app.inc").read_text()
            proxy = proxy.replace("127.0.0.1:8000", f"127.0.0.1:{backend.server_port}")
            (root / "proxy_app.inc").write_text(proxy)
            config = (repo / "deploy/nginx/host/dev/dev.procollab.ru").read_text()
            # Change only test environment paths/ports, retaining all routing rules.
            replacements = {
                "listen 80;": f"listen 127.0.0.1:{http_port};",
                "listen 443 ssl;": f"listen 127.0.0.1:{https_port} ssl;",
                "/home/front/app": root.as_posix(),
                "/etc/nginx/procollab/includes/proxy_app.inc": (root / "proxy_app.inc").as_posix(),
                "/etc/letsencrypt/live/dev.procollab.ru-0001/fullchain.pem": (root / "cert.pem").as_posix(),
                "/etc/letsencrypt/live/dev.procollab.ru-0001/privkey.pem": (root / "key.pem").as_posix(),
            }
            for source, target in replacements.items():
                config = config.replace(source, target)
            config = (
                f"pid {root}/nginx.pid;\nerror_log stderr;\nevents {{}}\n"
                f"http {{\naccess_log off;\n{temp_paths}{config}\n}}\n"
            )
            config_path = root / "nginx.conf"
            config_path.write_text(config)
            command = ["nginx", "-p", root.as_posix() + "/", "-c", str(config_path)]
            subprocess.run([*command, "-t"], check=True)
            with (root / "nginx.log").open("w+") as log:
                nginx = subprocess.Popen([*command, "-g", "daemon off;"], stdout=log, stderr=log)
                try:
                    context = ssl._create_unverified_context()  # Disposable self-signed certificate only.
                    base_url = f"https://127.0.0.1:{https_port}"
                    for _ in range(50):
                        try:
                            request(base_url, "/", context=context)
                            break
                        except OSError:
                            if nginx.poll() is not None:
                                log.seek(0)
                                self.fail(log.read())
                            time.sleep(0.1)
                    check_routes(base_url, context)
                    # Unknown auth URLs and protected APIs never fall through to SPA.
                    for path in (
                        "/auth/unknown/", "/auth/login/unrecognized/", "/programs/6/",
                        "/solution-invitations/123/", "/solution-invitations/123/accept/",
                        "/solution-form-templates/unknown/",
                    ):
                        status, content_type, body = request(base_url, path, context=context)
                        self.assertEqual((status, content_type), (404, "application/json"))
                        self.assertEqual(json.loads(body)["backend_path"], path)
                    status, content_type, body = request(base_url, "/solution-invitations-about", context=context)
                    self.assertEqual((status, content_type), (200, "text/html"))
                    self.assertIn(b"<app-root", body)
                    status, _, body = request(base_url, "/asset.js", context=context)
                    self.assertEqual((status, body), (200, b"window.fixture = true;"))
                finally:
                    nginx.terminate()
                    nginx.wait(timeout=10)


if __name__ == "__main__":
    unittest.main()
