"""HTTP client for the Transcriber API. Standard library only."""

import json
import os
import urllib.error
import urllib.parse
import urllib.request
import uuid

DEFAULT_URL = "http://127.0.0.1:8000"
TIMEOUT_SECONDS = 30
CHUNK_BYTES = 1024 * 1024


class ApiError(Exception):
    """The API refused, or could not be reached (status 0)."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def connection_failure(base_url: str, exc: Exception) -> ApiError:
    """The ApiError for a request that never got an answer."""
    refused = isinstance(exc, ConnectionRefusedError) or isinstance(
        getattr(exc, "reason", None), ConnectionRefusedError
    )
    if refused:
        return ApiError(
            0,
            f"Transcriber is not running at {base_url}. "
            "Start it with ./start.ps1 (Windows) or ./start.sh.",
        )
    reason = getattr(exc, "reason", None) or exc
    return ApiError(0, f"Cannot reach Transcriber at {base_url}: {reason}")


def urllib_transport(method, url, headers, body):
    """Send one request. Returns (status, body bytes); an HTTP error status is a result."""
    request = urllib.request.Request(url, data=body, method=method, headers=headers)
    # An upload can take as long as the disk needs; everything else answers quickly.
    timeout = TIMEOUT_SECONDS if body is None or isinstance(body, bytes) else None
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()


def _error_message(status: int, body: bytes) -> str:
    text = body.decode("utf-8", errors="replace")
    try:
        detail = json.loads(text).get("detail")
    except (ValueError, AttributeError):
        return text.strip() or f"HTTP {status}"
    if isinstance(detail, str):
        return detail
    if isinstance(detail, dict) and isinstance(detail.get("message"), str):
        return detail["message"]
    return text.strip() or f"HTTP {status}"


class Api:
    def __init__(self, base_url: str | None = None, transport=None):
        """base_url defaults to $TRANSCRIBER_URL, then DEFAULT_URL.

        transport(method, url, headers, body) -> (status, bytes); defaults to urllib.
        """
        self.base_url = (base_url or os.environ.get("TRANSCRIBER_URL") or DEFAULT_URL).rstrip("/")
        self.transport = transport or urllib_transport

    def get(self, path, **params):
        return self._json("GET", path, params=params)

    def post(self, path, json=None):
        return self._json("POST", path, body=json)

    def put(self, path, json=None):
        return self._json("PUT", path, body=json)

    def delete(self, path):
        return self._json("DELETE", path)

    def raw(self, path, **params) -> bytes:
        return self._send("GET", path, params=params)

    def upload(self, path, fields: dict, files: dict):
        """POST multipart/form-data, streaming each file in 1 MiB chunks."""
        boundary = uuid.uuid4().hex
        parts = []  # (preamble bytes, file path or None)
        for name, value in fields.items():
            head = (
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'
                f"{value}\r\n"
            )
            parts.append((head.encode("utf-8"), None))
        for name, file_path in files.items():
            filename = os.path.basename(file_path).replace('"', "_")
            head = (
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'
                "Content-Type: application/octet-stream\r\n\r\n"
            )
            parts.append((head.encode("utf-8"), file_path))
        epilogue = f"--{boundary}--\r\n".encode("ascii")

        length = len(epilogue)
        for head, file_path in parts:
            length += len(head)
            if file_path is not None:
                length += os.path.getsize(file_path) + 2  # the CRLF after the file

        def body():
            for head, file_path in parts:
                yield head
                if file_path is not None:
                    with open(file_path, "rb") as handle:
                        while chunk := handle.read(CHUNK_BYTES):
                            yield chunk
                    yield b"\r\n"
            yield epilogue

        headers = {
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Content-Length": str(length),
        }
        return self._decode(self._send("POST", path, headers=headers, body=body()))

    def _json(self, method, path, params=None, body=None):
        headers = {}
        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        return self._decode(self._send(method, path, params=params, headers=headers, body=data))

    @staticmethod
    def _decode(content: bytes):
        return json.loads(content.decode("utf-8")) if content else None

    def _send(self, method, path, params=None, headers=None, body=None) -> bytes:
        url = self.base_url + path
        query = {k: v for k, v in (params or {}).items() if v is not None}
        if query:
            url += "?" + urllib.parse.urlencode(query)
        try:
            status, content = self.transport(method, url, dict(headers or {}), body)
        except (ConnectionError, urllib.error.URLError, TimeoutError) as exc:
            raise connection_failure(self.base_url, exc) from exc
        if status >= 400:
            raise ApiError(status, _error_message(status, content))
        return content
