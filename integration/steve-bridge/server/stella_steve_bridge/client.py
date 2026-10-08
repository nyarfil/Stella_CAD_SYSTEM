"""Loopback-only HTTP client for the STEVE seam. The only network code on the Stella side."""
import http.client
import json

MAX_RESPONSE_BYTES = 512 * 1024


class BridgeUnavailable(Exception):
    pass


class SeamClient:
    def __init__(self, port, token, host="127.0.0.1"):
        if host != "127.0.0.1":
            raise ValueError("the bridge only talks to 127.0.0.1")
        self.port, self.token, self.host = port, token, host

    def call(self, route, body=None, timeout=60.0):
        data = json.dumps(body or {}).encode("utf-8")
        conn = http.client.HTTPConnection(self.host, self.port, timeout=timeout)
        try:
            conn.request("POST", "/v1/" + route, body=data, headers={
                "Authorization": "Bearer " + self.token, "Content-Type": "application/json",
                "Content-Length": str(len(data))})
            response = conn.getresponse()
            raw = response.read(MAX_RESPONSE_BYTES + 1)
            if len(raw) > MAX_RESPONSE_BYTES:
                return response.status, {"ok": False, "errorCode": "response_too_large",
                                         "error": "Seam response exceeded the cap."}
            try:
                payload = json.loads(raw.decode("utf-8"))
            except ValueError:
                return response.status, {"ok": False, "errorCode": "bad_response", "error": "Seam returned non-JSON."}
            return response.status, payload
        except (OSError, http.client.HTTPException) as exc:
            raise BridgeUnavailable(str(exc)[:200])
        finally:
            conn.close()
