"""Small inspectable mechanism catalog. Retrieval is lexical, not semantic AI."""
from __future__ import annotations
import json
import math
import re
from collections import Counter
from importlib.resources import files
from .errors import BrainError


def tokens(text: str):
    words = re.findall(r"[a-z0-9_]+|[\u3040-\u30ff\u3400-\u9fff]+", text.lower())
    result = []
    for w in words:
        if re.fullmatch(r"[a-z0-9_]+", w):
            result.append(w)
        else:
            result.extend(w[i:i+2] for i in range(max(1, len(w)-1)))
    return result


class Catalog:
    def __init__(self):
        data = json.loads(files("cadmcp_brain.data").joinpath("patterns.json").read_text("utf-8"))
        self.items = {p["id"]: p for p in data["patterns"]}
        if len(self.items) != len(data["patterns"]):
            raise BrainError("CATALOG_ERROR", "Duplicate pattern IDs")

    def get(self, pattern_id):
        if pattern_id not in self.items:
            raise BrainError("UNKNOWN_PATTERN", "Unknown mechanism pattern; register reviewed knowledge rather than inventing its ID.", {"pattern_id": pattern_id})
        return self.items[pattern_id]

    def search(self, query: str, limit: int = 6, function: str | None = None):
        if not 1 <= limit <= 20:
            raise BrainError("INVALID_LIMIT", "limit must be between 1 and 20")
        candidates = [p for p in self.items.values() if function is None or function in p["functions"]]
        docs = [Counter(tokens(json.dumps(p, ensure_ascii=False))) for p in candidates]
        q = set(tokens(query))
        scored = []
        for p, d in zip(candidates, docs):
            score = sum((1+math.log(d[t])) * math.log(1+(len(docs)+1)/(1+sum(t in x for x in docs))) for t in q if t in d)
            if score or not query.strip():
                scored.append({"lexical_score": round(score, 5), "pattern": p})
        return sorted(scored, key=lambda x: (-x["lexical_score"], x["pattern"]["id"]))[:limit]
