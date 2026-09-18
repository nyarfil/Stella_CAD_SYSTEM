"""Opt-in AgentCAD HTTP adapter using the upstream's discovered tool registry.

No model-selected URLs, no redirects, no automatic retries, no shell execution.
The owner must explicitly allow each callable tool in the process environment.
"""
from __future__ import annotations
import copy
import json
from urllib.request import Request, build_opener, HTTPRedirectHandler, ProxyHandler
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, quote
from jsonschema import Draft202012Validator
from .errors import BrainError
from .util import canonical, digest, safe_id


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise BrainError("BACKEND_REDIRECT","Refusing a backend redirect.")


class AgentCADClient:
    def __init__(self,base_url: str | None,allowed_tools=(),timeout=30):
        self.base_url=(base_url or "").rstrip("/")
        self.allowed_tools=frozenset(allowed_tools)
        self.timeout=timeout
        if self.base_url:
            u=urlsplit(self.base_url)
            if u.scheme not in ("http","https") or u.hostname not in ("127.0.0.1","localhost","::1") or u.username or u.password or u.path not in ("", "/") or u.query or u.fragment:
                raise BrainError("BACKEND_URL","Configure only a loopback AgentCAD origin, without credentials or a path.")
        self.opener=build_opener(ProxyHandler({}),NoRedirect())

    def request(self,path,payload=None):
        if not self.base_url:
            raise BrainError("BACKEND_DISABLED","No backend configured. Host-mediated CAD execution remains available.")
        req=Request(self.base_url+path,data=None if payload is None else canonical(payload).encode("utf-8"),headers={"Accept":"application/json","Content-Type":"application/json"},method="GET" if payload is None else "POST")
        try:
            with self.opener.open(req,timeout=self.timeout) as response:
                raw=response.read(4*1024*1024+1)
            if len(raw)>4*1024*1024: raise BrainError("BACKEND_RESPONSE_SIZE","Backend response exceeds 4 MiB.")
            return json.loads(raw)
        except HTTPError as exc:
            raise BrainError("BACKEND_HTTP_ERROR",f"Backend returned HTTP {exc.code}.",{"outcome_unknown":payload is not None}) from exc
        except (URLError,TimeoutError,OSError) as exc:
            raise BrainError("BACKEND_TRANSPORT_ERROR","Backend request did not complete. Do not automatically retry a write.",{"outcome_unknown":payload is not None,"reason":str(exc)[:1000]}) from exc
        except (ValueError,UnicodeDecodeError) as exc:
            raise BrainError("BACKEND_BAD_JSON","Backend returned non-JSON content.",{"outcome_unknown":payload is not None}) from exc

    def probe(self):
        result=self.request("/api/tools")
        if not isinstance(result,dict) or not isinstance(result.get("tools"),list):
            raise BrainError("BACKEND_SCHEMA_DRIFT","Expected an AgentCAD object containing a tools array; integration is blocked, not guessed.")
        tools=[]
        for t in result["tools"]:
            if not isinstance(t,dict) or not isinstance(t.get("name"),str):
                raise BrainError("BACKEND_SCHEMA_DRIFT","Malformed discovered tool.")
            # Both spellings are explicit registry/wire representations, not guessed tool names.
            schema=t.get("input_schema",t.get("inputSchema"))
            if not isinstance(schema,dict):
                raise BrainError("BACKEND_SCHEMA_DRIFT","Discovered tool has no supported input schema.",{"tool":t["name"]})
            tools.append({"name":t["name"],"description":t.get("description",""),"input_schema":schema,"owner_allowed":t["name"] in self.allowed_tools})
        if len({t["name"] for t in tools})!=len(tools):
            raise BrainError("BACKEND_SCHEMA_DRIFT","Duplicate tool names.")
        return {"backend":"AgentCAD","tools":tools,"registry_digest":digest(tools),"writes_enabled_only_for_owner_allowlist":True}

    def prepare(self,tool,arguments):
        safe_id(tool)
        if tool not in self.allowed_tools:
            raise BrainError("BACKEND_TOOL_DENIED","Tool is not in the owner's allowlist; the model cannot grant itself permission.",{"tool":tool})
        registry=self.probe()
        found=next((t for t in registry["tools"] if t["name"]==tool),None)
        if found is None:
            raise BrainError("BACKEND_UNKNOWN_TOOL","Tool is not in the live backend registry.")
        schema=copy.deepcopy(found["input_schema"])
        def reject_external_refs(obj):
            if isinstance(obj,dict):
                for k,v in obj.items():
                    if k in ("$ref","$dynamicRef") and (not isinstance(v,str) or not v.startswith("#")):
                        raise BrainError("BACKEND_SCHEMA_REF","External schema references are not fetched.")
                    reject_external_refs(v)
            elif isinstance(obj,list):
                for v in obj: reject_external_refs(v)
        reject_external_refs(schema)
        schema.setdefault("additionalProperties",False)
        # AgentCAD's documented optional-null semantics: null means omitted.
        required=set(schema.get("required",[]))
        normalized={k:v for k,v in arguments.items() if v is not None or k in required}
        try:
            Draft202012Validator.check_schema(schema)
            errors=sorted(Draft202012Validator(schema).iter_errors(normalized),key=lambda e:str(e.path))
        except Exception as exc:
            raise BrainError("BACKEND_SCHEMA_DRIFT","The backend schema cannot be validated.",{"reason":str(exc)[:1000]}) from exc
        if errors:
            raise BrainError("BACKEND_ARGUMENTS","Arguments do not match the discovered schema.",{"errors":[e.message for e in errors[:20]]})
        return {"tool":tool,"arguments":normalized,"registry_digest":registry["registry_digest"]}

    def execute_prepared(self,prepared):
        result=self.request("/api/tools/"+quote(prepared["tool"],safe=""),prepared["arguments"])
        # HTTP 200 can contain a failed AgentCAD operation.
        if not isinstance(result,dict):
            raise BrainError("BACKEND_BAD_RESULT","Expected an object result.",{"outcome_unknown":True})
        if result.get("error") is not None or result.get("ok") is False:
            return {"status":"backend_reported_error","result":result,"automatic_retry":False}
        return {"status":"backend_returned","result":result,"geometrically_verified":False}
