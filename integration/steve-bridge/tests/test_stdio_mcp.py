"""Drive the real server process over stdio as a generic MCP client (host-neutrality proof)."""
import json
import os
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENTRY = os.path.join(ROOT, "server", "stella_steve_bridge_mcp.py")


class McpClient:
    def __init__(self, args):
        self.proc = subprocess.Popen([sys.executable, "-I", ENTRY] + args, stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.next_id = 0
        self.raw_lines = []

    def send(self, obj):
        self.proc.stdin.write((json.dumps(obj) + "\n").encode())
        self.proc.stdin.flush()

    def request(self, method, params=None):
        self.next_id += 1
        self.send({"jsonrpc": "2.0", "id": self.next_id, "method": method, "params": params or {}})
        line = self.proc.stdout.readline()
        self.raw_lines.append(line)
        message = json.loads(line)
        assert message["id"] == self.next_id
        return message

    def close(self):
        self.proc.stdin.close()
        self.proc.wait(timeout=10)
        rest = self.proc.stdout.read()
        self.raw_lines.append(rest)
        return self.proc.stderr.read().decode()


@pytest.fixture
def client(env):
    c = McpClient(["--allow-document", "SANDBOX", "--home", str(env.home), "--port", str(env.port),
                   "--scratch-dir", str(env.home / "scratch")])
    yield c
    if c.proc.poll() is None:
        c.close()


@pytest.mark.parametrize("version", ["2024-11-05", "2025-03-26", "2025-06-18", "2099-01-01"])
def test_initialize_negotiates_version(client, version):
    reply = client.request("initialize", {"protocolVersion": version, "capabilities": {},
                                          "clientInfo": {"name": "generic-test", "version": "0"}})
    result = reply["result"]
    assert result["protocolVersion"] == (version if version != "2099-01-01" else "2025-06-18")
    assert "tools" in result["capabilities"] and result["serverInfo"]["name"]


def test_full_flow_initialize_list_call(client, env):
    client.request("initialize", {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "x", "version": "1"}})
    client.send({"jsonrpc": "2.0", "method": "notifications/initialized"})   # no reply expected
    listed = client.request("tools/list")["result"]["tools"]
    names = {t["name"] for t in listed}
    assert {"stella_fusion_inspect", "stella_fusion_query", "stella_fusion_execute", "stella_fusion_viewport",
            "stella_fusion_health"} <= names
    for tool in listed:
        assert tool["description"].isascii() and tool["inputSchema"]["type"] == "object"
    health = client.request("tools/call", {"name": "stella_fusion_health", "arguments": {}})["result"]
    assert health["isError"] is False
    assert json.loads(health["content"][0]["text"])["ok"] is True
    run = client.request("tools/call", {"name": "stella_fusion_execute", "arguments": {
        "title": "t", "code": "def run(c):\n    return to_cm(10)\n"}})["result"]
    assert run["isError"] is False and json.loads(run["content"][0]["text"])["result"] == 1.0
    assert env.app.execute_failed_flags == [False]


def test_error_semantics(client):
    client.request("initialize", {"protocolVersion": "2025-06-18"})
    denied = client.request("tools/call", {"name": "stella_fusion_execute", "arguments": {
        "title": "t", "code": "import subprocess\ndef run(c):\n    pass\n"}})["result"]
    assert denied["isError"] is True and "denied_code_policy" in denied["content"][0]["text"]
    bad_args = client.request("tools/call", {"name": "stella_fusion_query", "arguments": {"title": "t"}})["result"]
    assert bad_args["isError"] is True
    unknown_tool = client.request("tools/call", {"name": "nope", "arguments": {}})
    assert unknown_tool["error"]["code"] == -32602
    assert client.request("no/such/method")["error"]["code"] == -32601
    assert client.request("ping")["result"] == {}


def test_stdout_contains_only_protocol_frames(client):
    client.request("initialize", {"protocolVersion": "2025-06-18"})
    client.request("tools/list")
    client.proc.stdin.write(b"this is not json\n")
    client.proc.stdin.flush()
    parse_error = json.loads(client.proc.stdout.readline())
    assert parse_error["error"]["code"] == -32700
    stderr = client.close()
    for line in client.raw_lines:
        for part in filter(None, line.splitlines()):
            assert json.loads(part)["jsonrpc"] == "2.0"
    assert isinstance(stderr, str)


def test_read_only_flag_over_stdio(env):
    c = McpClient(["--allow-document", "SANDBOX", "--read-only", "--home", str(env.home), "--port", str(env.port)])
    try:
        c.request("initialize", {"protocolVersion": "2025-06-18"})
        out = c.request("tools/call", {"name": "stella_fusion_execute", "arguments": {
            "title": "t", "code": "def run(c):\n    return 1\n"}})["result"]
        assert out["isError"] is True and "denied_read_only" in out["content"][0]["text"]
    finally:
        c.close()
