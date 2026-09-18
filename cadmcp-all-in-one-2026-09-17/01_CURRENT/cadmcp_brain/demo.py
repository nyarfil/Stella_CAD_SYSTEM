"""Executable authored fixture replay. Never presented as an autonomous LLM test."""
import json
from importlib.resources import files
from uuid import uuid4
from .engine import Brain


def fixture():
    return json.loads(files("cadmcp_brain.data").joinpath("demo.json").read_text("utf-8"))


def build_fixture_geometry(folder):
    import cadquery as cq
    folder.mkdir(parents=True,exist_ok=True)
    # Deliberately simple test solids. These are NOT a functional side-button assembly.
    cq.exporters.export(cq.Workplane("XY").box(20,10,2),str(folder/"frame.step"))
    cq.exporters.export(cq.Workplane("XY").box(8,2,2).translate((0,7,0)),str(folder/"button.step"))


def run_demo(brain: Brain,with_geometry=False):
    data=fixture(); pid="demo-"+uuid4().hex[:8]
    brain.open(pid,data["request"])
    brain.submit_intent(pid,0,data["brief"])
    evaluation=brain.submit_concepts(pid,1,data["concepts"])
    brain.select(pid,2,"C-direct")
    brain.submit_plan(pid,3,data["plan"])
    export=brain.export(pid,4)
    rev=4
    if with_geometry:
        rel="incoming/"+pid
        build_fixture_geometry(brain.store.root/rel)
        brain.import_step(pid,rev,"A-frame",rel+"/frame.step",export["contract_digest"]); rev+=1
        brain.import_step(pid,rev,"A-button",rel+"/button.step",export["contract_digest"]); rev+=1
    verification=brain.verify(pid,rev)
    return {"fixture_notice":data["notice"],"project_id":pid,"export":export,"evaluations":evaluation["evaluations"],"verification":verification,"llm_calls":0,"expected_overall":"unknown (manual and physical evidence deliberately absent)"}
