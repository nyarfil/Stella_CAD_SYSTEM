"""JSON-lines audit log. Stores the submitted code text (truncated if huge) in a local file only."""
import hashlib
import json
import os
import threading
import time

MAX_CODE_CHARS = 20000          # longer code is truncated in the log; code_sha256 always covers the full text
MAX_LOG_BYTES = 5 * 1024 * 1024  # rotate audit.jsonl -> .1 -> .2 -> .3
KEEP_ROTATED = 3


def sha256(text):
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


class AuditLog:
    def __init__(self, path, max_bytes=MAX_LOG_BYTES, keep=KEEP_ROTATED):
        self.path = path
        self.max_bytes = max_bytes
        self.keep = keep
        self._lock = threading.Lock()

    def _rotate(self):
        try:
            if os.path.getsize(self.path) < self.max_bytes:
                return
        except OSError:
            return
        for index in range(self.keep, 0, -1):
            source = self.path if index == 1 else "%s.%d" % (self.path, index - 1)
            if os.path.exists(source):
                os.replace(source, "%s.%d" % (self.path, index))

    def write(self, **entry):
        entry["ts"] = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + "Z"
        code = entry.get("code")
        if code is not None:
            entry["code_sha256"] = sha256(code)
            if len(code) > MAX_CODE_CHARS:
                entry["code"] = code[:MAX_CODE_CHARS]
                entry["code_truncated"] = True
                entry["code_chars"] = len(code)
        line = json.dumps(entry, ensure_ascii=False, sort_keys=True)
        with self._lock:
            os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
            self._rotate()
            with open(self.path, "a", encoding="utf-8") as handle:
                handle.write(line + "\n")
