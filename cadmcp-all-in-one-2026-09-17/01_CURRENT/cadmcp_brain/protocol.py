"""Bounded synchronous MCP stdio server (2025-06-18 tools/resources/prompts).

No HTTP server, sampling, elicitation, subscriptions, task extension or auth surface.
This deliberately small transport is tested on the wire. It is not the official SDK.
Long calls have worker/network timeouts; cancellation does not pre-empt a running call.
"""
from __future__ import annotations
import json
import sys
from pydantic import ValidationError
from . import __version__
from .errors import BrainError
from .util import canonical

PROTOCOL="2025-06-18"
MAX_FRAME=2*1024*1024
WORKFLOW="Structure-first CAD for a customer's solid parts, not a mouse-only factory. Read brain_fs_status; keep an empty/partial catalog distinct from a full Req2CAD installation. Req2CAD search is optional when similar structures help; a missing semantic index is not lexical success. For a mouse with PCB and shell, inspect workspace files, register a ready Board Pack and a ready Shell Pack, then read brain_mouse_structure_gate; a STEP on disk is not a shell pack and cylindrical CAD features are not screw holes. Scan-to-shell conversion is not this server. For structural design use brain_open → brain_studio_schema(FunctionBrief) → optional brain_fs_search_tasks → typed Recipe with real STEP (Req2CAD reference or registered project_step) → brain_studio_build → five evidence-based review roles → peer challenge → rebuild with frozen checks. Fusion assembly uses only brain_fusion_handoff's issued script via fusion_mcp_execute, then brain_fusion_ingest remesure; do not invent Fusion Python. Preserve owner-protected hardware. Legacy intent/contract tools remain available, but 13 authored cards do not replace real CAD references. STEP is always exported. No printer, canonical CAD write, or f3d save is automatic."


def strict_json(text):
    def pairs(items):
        result={}
        for k,v in items:
            if k in result: raise ValueError("duplicate JSON key")
            result[k]=v
        return result
    def reject(value): raise ValueError("non-finite JSON number")
    return json.loads(text,object_pairs_hook=pairs,parse_constant=reject)


class Protocol:
    def __init__(self,tools):
        self.tools=tools; self.initialized=False; self.negotiated=False

    def error(self,rid,code,message,data=None):
        e={"code":code,"message":message}
        if data is not None: e["data"]=data
        return {"jsonrpc":"2.0","id":rid,"error":e}

    def handle(self,msg):
        if not isinstance(msg,dict): return self.error(None,-32600,"Expected one JSON-RPC request object, not a batch")
        rid=msg.get("id"); notification="id" not in msg
        if msg.get("jsonrpc")!="2.0" or not isinstance(msg.get("method"),str) or (not notification and (isinstance(rid,bool) or not isinstance(rid,(str,int,type(None))))):
            return self.error(None,-32600,"Invalid JSON-RPC request")
        method=msg["method"]; params=msg.get("params",{})
        if not isinstance(params,dict): return None if notification else self.error(rid,-32602,"params must be an object")
        if notification:
            if method=="notifications/initialized" and self.negotiated: self.initialized=True
            # Notifications never produce responses. No subscription/sampling support is advertised.
            return None
        if method=="ping": return {"jsonrpc":"2.0","id":rid,"result":{}}
        if method=="initialize":
            if self.negotiated: return self.error(rid,-32600,"Already initialized")
            info=params.get("clientInfo")
            if not isinstance(params.get("protocolVersion"),str) or not isinstance(params.get("capabilities"),dict) or not isinstance(info,dict) or not isinstance(info.get("name"),str) or not isinstance(info.get("version"),str):
                return self.error(rid,-32602,"Missing initialization fields")
            self.negotiated=True
            return {"jsonrpc":"2.0","id":rid,"result":{"protocolVersion":PROTOCOL,"capabilities":{"tools":{},"prompts":{},"resources":{}},"serverInfo":{"name":"cadmcp-design-brain","version":__version__},"instructions":WORKFLOW}}
        if not self.initialized: return self.error(rid,-32002,"Initialize and send notifications/initialized first")
        try:
            if method=="tools/list":
                if params.get("cursor"): return self.error(rid,-32602,"Invalid pagination cursor")
                result={"tools":self.tools.list()}
            elif method=="tools/call":
                name=params.get("name"); arguments=params.get("arguments",{})
                if not isinstance(name,str) or not isinstance(arguments,dict): return self.error(rid,-32602,"Tool name and object arguments are required")
                if name not in self.tools.registry: return self.error(rid,-32602,"Unknown tool")
                try:
                    value={"ok":True,"result":self.tools.call(name,arguments)}
                except ValidationError as exc:
                    value={"ok":False,"error":{"code":"SCHEMA_VALIDATION","message":"Arguments or design IR do not match the schema.","details":exc.errors(include_url=False,include_context=False,include_input=False)}}
                except BrainError as exc:
                    value={"ok":False,"error":exc.as_dict()}
                result={"content":[{"type":"text","text":canonical(value)}],"structuredContent":value,"isError":not value["ok"]}
            elif method=="resources/list":
                result={"resources":[{"uri":"cadbrain://workflow","name":"Design workflow","mimeType":"text/plain"},{"uri":"cadbrain://patterns","name":"Authored mechanism catalog","mimeType":"application/json"}]+[{"uri":"cadbrain://schema/"+n,"name":n+" schema","mimeType":"application/json"} for n in ("Brief","Concepts","Concept","Plan")]}
            elif method=="resources/read":
                uri=params.get("uri","")
                if uri=="cadbrain://workflow": text=WORKFLOW; mime="text/plain"
                elif uri=="cadbrain://patterns": text=canonical(list(self.tools.brain.catalog.items.values())); mime="application/json"
                elif isinstance(uri,str) and uri.startswith("cadbrain://schema/"):
                    text=canonical(self.tools.brain_schema(uri.rsplit("/",1)[-1])); mime="application/json"
                else: return self.error(rid,-32002,"Unknown resource")
                result={"contents":[{"uri":uri,"mimeType":mime,"text":text}]}
            elif method=="prompts/list":
                result={"prompts":[{"name":"design_stage","description":"Source-grounded CAD design stage for the host model","arguments":[{"name":"project_id","required":True},{"name":"stage","required":False}]}]}
            elif method=="prompts/get":
                if params.get("name")!="design_stage": return self.error(rid,-32602,"Unknown prompt")
                args=params.get("arguments",{})
                if not isinstance(args,dict) or not isinstance(args.get("project_id"),str) or any(k not in ("project_id","stage") for k in args): return self.error(rid,-32602,"Invalid prompt arguments")
                task=self.tools.call("brain_task",args)
                result={"description":"CAD design stage","messages":[{"role":"user","content":{"type":"text","text":canonical(task)}}]}
            else: return self.error(rid,-32601,"Method not found")
            return {"jsonrpc":"2.0","id":rid,"result":result}
        except (BrainError,ValidationError) as exc:
            return self.error(rid,-32602,str(exc)[:2000])
        except Exception as exc:
            print(f"cadmcp-brain internal error: {type(exc).__name__}: {str(exc)[:500]}",file=sys.stderr,flush=True)
            return self.error(rid,-32603,"Internal server error; see stderr")


def serve(tools,inp=None,out=None):
    inp=inp or sys.stdin.buffer; out=out or sys.stdout.buffer
    protocol=Protocol(tools)
    while True:
        raw=inp.readline(MAX_FRAME+1)
        if not raw: return 0
        if len(raw)>MAX_FRAME:
            reply=protocol.error(None,-32700,"Frame exceeds 2 MiB")
            out.write((canonical(reply)+"\n").encode("utf-8")); out.flush()
            return 2
        try: msg=strict_json(raw.decode("utf-8")); reply=protocol.handle(msg)
        except (ValueError,UnicodeError,RecursionError): reply=protocol.error(None,-32700,"Invalid UTF-8 JSON")
        if reply is not None:
            try: encoded=(canonical(reply)+"\n").encode("utf-8")
            except (ValueError,RecursionError): encoded=(canonical(protocol.error(msg.get("id") if isinstance(msg,dict) else None,-32603,"Nonserializable result"))+"\n").encode()
            try:
                out.write(encoded); out.flush()
            except BrokenPipeError: return 0
