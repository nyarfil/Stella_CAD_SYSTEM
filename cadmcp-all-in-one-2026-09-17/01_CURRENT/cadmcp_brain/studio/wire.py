"""Encode typed maps as key/value arrays for closed structured-output schemas.

JSON Schema permits dynamic object keys; model structured-output interfaces can
require every object to have additionalProperties=false. The wire format closes
those objects without losing user-chosen CAD function/parameter names. Duplicate
keys are rejected instead of silently overwritten. Native models stay unchanged.
"""
from __future__ import annotations
import copy
import jsonschema

def map_value_schema(schema):
    if isinstance(schema.get('additionalProperties'),dict):return schema['additionalProperties'],None
    patterns=schema.get('patternProperties',{})
    if len(patterns)==1:
        pattern,value=next(iter(patterns.items()));return value,pattern
    return None,None


def output_schema(schema):
    def visit(node):
        if isinstance(node,list):return [visit(x) for x in node]
        if not isinstance(node,dict):return node
        n={k:visit(v) for k,v in node.items() if k not in {'default','discriminator','minProperties','maxProperties'}}
        if 'const' in n:n['enum']=[n.pop('const')]
        if 'oneOf' in n:n['anyOf']=n.pop('oneOf')
        if node.get('type')=='object':
            if 'properties' in node:
                n['required']=list(node['properties']);n['additionalProperties']=False
            elif map_value_schema(node)[0] is not None:
                n={'type':'array','description':node.get('description','Named map encoded as distinct key/value entries.'),
                   'items':{'type':'object','additionalProperties':False,'properties':{
                       'key':{'type':'string',**({'pattern':map_value_schema(node)[1]} if map_value_schema(node)[1] else {})},'value':visit(map_value_schema(node)[0])},'required':['key','value']}}
            else:n.update(properties={},required=[],additionalProperties=False)
        return n
    return visit(copy.deepcopy(schema))

def decode(value,schema):
    root=schema
    def run(v,s):
        if '$ref' in s:
            if not s['$ref'].startswith('#/$defs/'):raise ValueError('Only local definitions are supported.')
            return run(v,root['$defs'][s['$ref'].split('/')[-1]])
        variants=s.get('anyOf',s.get('oneOf'))
        if variants:
            for variant in variants:
                try:
                    result=run(v,variant)
                    jsonschema.Draft202012Validator({'$defs':root.get('$defs',{}),**variant}).validate(result)
                    return result
                except (ValueError,TypeError,KeyError,jsonschema.ValidationError):pass
            raise ValueError('No schema alternative accepts this structured output.')
        if s.get('type')=='object' and 'properties' not in s and map_value_schema(s)[0] is not None:
            if not isinstance(v,list):raise ValueError('Map wire value must be an array of key/value entries.')
            out={}
            for entry in v:
                if not isinstance(entry,dict) or set(entry)!={'key','value'} or not isinstance(entry['key'],str):raise ValueError('Malformed map entry.')
                if entry['key'] in out:raise ValueError('Duplicate map key in model output.')
                value_schema,pattern=map_value_schema(s)
                if pattern:
                    import re
                    if not re.search(pattern,entry['key']):raise ValueError('Invalid map key.')
                out[entry['key']]=run(entry['value'],value_schema)
            return out
        if s.get('type')=='object':
            if not isinstance(v,dict):raise ValueError('Expected object.')
            return {k:run(x,s.get('properties',{}).get(k,{})) for k,x in v.items()}
        if s.get('type')=='array':
            if not isinstance(v,list):raise ValueError('Expected array.')
            return [run(x,s.get('items',{})) for x in v]
        return v
    result=run(value,schema)
    jsonschema.Draft202012Validator(schema).validate(result)
    return result
