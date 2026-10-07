"""Synthetic interval checks; numbers are not any manufacturer's switch specs."""
from __future__ import annotations
import copy
import unittest
import jsonschema
from test_mcp import session, tool, value
from mouse_library.click_window import INPUT_SCHEMA, ALLOWABLE_DEFINITION, evaluate

def example():
    values={'gap':(.15,.2),'rest_closure':(0,0),'pre_stop_closure':(.65,.7),
        'post_stop_closure':(.75,.8),'on_compression':(.35,.4),'off_compression':(.15,.2),
        'allowable_compression':(.7,.8),'on_margin':(.05,.05),'release_margin':(.02,.02),
        'safety_margin':(.05,.05),'design_load':(2,2)}
    quantities={name:{'min':low,'max':high,'unit':'N' if name=='design_load' else 'mm',
        'source':{'kind':'proposed','evidence_ref':'synthetic arithmetic fixture, not a hardware specification',
                  'hardware_scope':'Generic board Alpha; hypothetical switch'}} for name,(low,high) in values.items()}
    quantities['allowable_compression']['definition']=ALLOWABLE_DEFINITION
    return {'hardware_id':'Generic board Alpha; hypothetical switch',
        'coordinate_basis':'One common u=0 reference and downward plunger axis; g excludes closure error already included in u.',
        'state_context':{'rest_closure':'After actuation and release, at returned rest; no return-force proof.',
            'pre_stop_closure':'Immediately before lower-stop contact.',
            'post_stop_closure':'After lower-stop contact at supplied 2 N design load; hypothetical relative support deflection included.'},
        'quantities':quantities}

class ClickWindowAcceptance(unittest.TestCase):
    def test_generic_schema_and_equal_boundaries(self):
        args=example()
        jsonschema.validate(args,INPUT_SCHEMA)
        result=evaluate(args)
        self.assertEqual(result['status'],'interval_conditions_hold')
        self.assertEqual(result['gap_window']['lower_decimal_mm'],'0.15')
        self.assertEqual(result['gap_window']['upper_decimal_mm'],'0.20')
        self.assertFalse(result['physical_design_complete'])
        self.assertEqual(len(result['assumption_inputs']),11)
        self.assertEqual(result['conditions'][0]['slack_decimal_mm'],'0.00')

    def test_missing_and_known_failure_are_separate(self):
        args=example()
        args['quantities'].pop('allowable_compression')
        result=evaluate(args)
        self.assertEqual(result['status'],'not_evaluated_missing_inputs')
        self.assertEqual(result['conditions'][2]['status'],'not_evaluated')
        args['quantities']['gap']['max']=.3
        result=evaluate(args)
        self.assertEqual(result['status'],'interval_conditions_not_satisfied')
        self.assertFalse(result['conditions'][0]['holds_for_supplied_bounds'])

    def test_negative_gap_preload_and_impossible_window(self):
        args=example()
        args['quantities']['gap'].update(min=-.2,max=-.1)
        result=evaluate(args)
        self.assertEqual(result['compression_extrema_mm']['rest_max'],.2)
        self.assertFalse(result['conditions'][1]['holds_for_supplied_bounds'])
        args=example()
        args['quantities']['safety_margin'].update(min=.8,max=.8)
        self.assertFalse(evaluate(args)['gap_window']['feasible_for_supplied_bounds'])

    def test_current_gap_failure_does_not_erase_feasible_design_window(self):
        args=example()
        args['quantities']['gap']['max']=.3
        result=evaluate(args)
        self.assertEqual(result['status'],'interval_conditions_not_satisfied')
        self.assertTrue(result['gap_window']['feasible_for_supplied_bounds'])
        self.assertEqual(result['gap_window']['upper_decimal_mm'],'0.20')

    def test_threshold_order_and_state_context_not_invented(self):
        args=example()
        args['quantities']['off_compression']['max']=.4
        self.assertEqual(evaluate(args)['status'],'not_evaluated_threshold_order')
        args=example()
        args['state_context'].pop('post_stop_closure')
        self.assertIn('state_context.post_stop_closure',evaluate(args)['missing_inputs'])
        self.assertIsNone(evaluate(args)['conditions'][2]['holds_for_supplied_bounds'])

    def test_contradicted_threshold_and_impossible_monotonic_budget(self):
        args=example()
        args['quantities']['off_compression'].update(min=.5,max=.6)
        self.assertEqual(evaluate(args)['threshold_order_status'],'contradicted')
        self.assertEqual(evaluate(args)['status'],'interval_conditions_not_satisfied')
        args=example()
        args['quantities']['on_margin'].update(min=.4,max=.4)
        args['quantities']['pre_stop_closure'].update(min=1,max=1)
        args['quantities']['post_stop_closure'].update(min=.5,max=.5)
        result=evaluate(args)
        self.assertTrue(all(c['holds_for_supplied_bounds'] for c in result['conditions']))
        self.assertEqual(result['status'],'interval_conditions_not_satisfied')
        self.assertFalse(result['gap_window']['feasible_for_supplied_bounds'])
        self.assertEqual(result['post_stop_load_context']['design_load_interval_N'],[2,2])

    def test_bad_numeric_units_and_minimum_overtravel_rejected(self):
        for invalid in (True,'0.1',float('nan'),float('inf'),10**1000):
            args=example(); args['quantities']['gap']['min']=invalid
            with self.assertRaises(ValueError): evaluate(args)
        for name,changes in [('gap',{'min':1,'max':0}),('gap',{'unit':'cm'}),
            ('on_margin',{'min':-.1}),('on_compression',{'min':0}),
            ('allowable_compression',{'definition':'minimum_overtravel'})]:
            args=example(); args['quantities'][name].update(changes)
            with self.assertRaises(ValueError): evaluate(args)

    def test_standalone_and_native_real_mcp(self):
        import tempfile
        args=example()
        standalone,_=session([tool('mouse_library_click_window',args)])
        result=value(standalone[1])
        self.assertEqual(result['status'],'interval_conditions_hold')
        self.assertEqual(len(result['calculation_code_sha256']),64)
        with tempfile.TemporaryDirectory(prefix='stella-generic-click-') as tmp:
            native,_=session([tool('brain_mouse_knowledge_schema',{'name':'click_window'}),
                tool('brain_mouse_knowledge_click_window',{'assessment':args})],stella_workspace=tmp)
        jsonschema.validate(args,value(native[1])['schema'])
        self.assertEqual(value(native[2])['input_sha256'],result['input_sha256'])
        self.assertFalse(value(native[2])['physical_design_complete'])
        bad=copy.deepcopy(args); bad['quantities']['gap']['unit']='cm'
        response,_=session([tool('mouse_library_click_window',bad)])
        self.assertTrue(response[1]['result']['isError'])
