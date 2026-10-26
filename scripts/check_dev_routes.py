"""Read-only SPA/API routing smoke check (empty reset payloads send no mail)."""

import argparse
import json
import sys
from urllib.error import HTTPError
from urllib.request import Request, urlopen


AUTH_PAGES = (
    "/auth",
    "/auth/login",
    "/auth/register",
    "/auth/verification",
    "/auth/verification/email",
    "/auth/reset_password",
    "/auth/reset_password/send_email",
    "/auth/reset_password/confirm",
)


def request(base_url, path, method="GET", context=None):
    data = b"{}" if method == "POST" else None
    req = Request(base_url + path, data=data, method=method, headers={"Content-Type": "application/json"})
    try:
        response = urlopen(req, timeout=15, context=context)
    except HTTPError as error:
        response = error
    with response:
        return response.status, response.headers.get_content_type(), response.read()


def check_routes(base_url, context=None):
    status, content_type, index = request(base_url, "/", context=context)
    assert status == 200 and content_type == "text/html" and b"<app-root" in index, "SPA index unavailable"
    for path in (*AUTH_PAGES, "/office/program/all", "/expert-password-reset/"):
        for suffix in ("", "/") if not path.endswith("/") else ("",):
            page = path + suffix + "?routing_check=1"
            for method in ("GET", "HEAD"):
                status, content_type, body = request(base_url, page, method, context)
                assert status == 200 and content_type == "text/html", (method, page, status, content_type)
                assert body == (index if method == "GET" else b""), (method, page, "not the SPA index")
        sys.stdout.write(f"SPA GET/HEAD OK: {path}\n")

    # These invalid requests cannot send reset email or change a password.
    for path, method, expected in (
        ("/auth/users/current/", "GET", 401),
        ("/solution-invitations/?status=pending&limit=100&offset=0", "GET", 401),
        ("/solution-form-templates/", "GET", 401),
        ("/auth/reset_password/", "POST", 400),
        ("/auth/reset_password/confirm/", "POST", 400),
        ("/auth/reset_password/validate_token/", "POST", 400),
        ("/api/token/", "POST", 400),
    ):
        status, content_type, body = request(base_url, path, method, context)
        assert status == expected and content_type == "application/json", (method, path, status, content_type)
        json.loads(body)
        sys.stdout.write(f"API {method} OK: {path} ({status})\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("base_url")
    args = parser.parse_args()
    check_routes(args.base_url.rstrip("/"))
