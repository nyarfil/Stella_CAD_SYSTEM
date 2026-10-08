from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import route_backend as router
import select_backend as selector


class RoutingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.project = Path(self.temp.name).resolve()
        self.available = patch('cadmcp_brain.studio.backend_routing.geometry.available', return_value=True)
        self.available.start()

    def tearDown(self):
        self.available.stop()
        self.temp.cleanup()

    def test_auto_plan_activate_and_repeat(self):
        router.set_auto(self.project, ['cadquery', 'freecad', 'build123d'])
        before = sorted(self.project.rglob('*'))
        result = router.plan(self.project, ['box'], ['bbox'], [])
        self.assertEqual(result['decision']['selected_backend'], 'cadquery')
        self.assertEqual(before, sorted(self.project.rglob('*')))
        activated = router.plan(self.project, ['box'], ['bbox'], [], activate=True)
        self.assertTrue(activated['activated'])
        self.assertEqual(selector.read_selection(self.project)['selection_mode'], 'capability_auto')
        self.assertEqual(router.plan(self.project, ['box'], [], [])['decision']['mode'], 'auto')

    def test_explicit_selection_wins_over_auto_policy(self):
        selector.select_backend(self.project, 'classcad')
        router.set_auto(self.project, ['cadquery', 'freecad'])
        result = router.plan(self.project, ['box'], [], [])
        self.assertEqual(result['decision']['status'], 'selected_backend_unavailable')
        self.assertEqual(selector.read_selection(self.project)['backend'], 'classcad')

    def test_not_selected_and_advanced_unprobed_block(self):
        self.assertEqual(router.plan(self.project, ['box'], [], [])['decision']['status'], 'selection_required')
        router.set_auto(self.project, ['cadquery', 'freecad'])
        with self.assertRaises(selector.SelectionError):
            router.plan(self.project, ['shell'], [], [], activate=True)
        self.assertIsNone(selector.read_selection(self.project))

    def test_freecad_probe_without_project_kit_is_not_ready(self):
        router.set_auto(self.project, ['freecad'])
        probe = {'backend': 'freecad', 'operations': ['shell'], 'installed': True,
                 'ready': True, 'evidence': 'test', 'cost': 'free'}
        self.assertEqual(router.plan(self.project, ['shell'], [], [probe])['decision']['status'], 'no_capable_backend')

    def test_selection_race_rejected(self):
        policy = router.set_auto(self.project, ['cadquery'])['policy']
        decision = router.plan(self.project, ['box'], [], [])['decision']
        selector.select_backend(self.project, 'fusion')
        with self.assertRaisesRegex(selector.SelectionError, 'selection changed'):
            selector.select_backend(self.project, 'cadquery', routing_decision=decision,
                                    expected_selection=None, expected_routing_policy=policy)
        self.assertEqual(selector.read_selection(self.project)['backend'], 'fusion')

    def test_policy_race_rejected(self):
        policy = router.set_auto(self.project, ['cadquery'])['policy']
        decision = router.plan(self.project, ['box'], [], [])['decision']
        router.set_auto(self.project, ['freecad'])
        with self.assertRaisesRegex(selector.SelectionError, 'policy changed'):
            selector.select_backend(self.project, 'cadquery', routing_decision=decision,
                                    expected_selection=None, expected_routing_policy=policy)
        self.assertIsNone(selector.read_selection(self.project))

    def test_build123d_selection_keeps_external_mcp_writers_disabled(self):
        result = selector.select_backend(self.project, 'build123d')
        self.assertEqual(result['activation']['enabled_writer_servers'], [])
        self.assertEqual(selector.read_selection(self.project)['backend_config']['mcp_server'], 'cadgen-cli')

    def test_forged_decision_cannot_bypass_allowlist(self):
        policy = router.set_auto(self.project, ['cadquery'])['policy']
        forged = {'mode': 'auto', 'status': 'ready', 'selected_backend': 'fusion'}
        with self.assertRaisesRegex(selector.SelectionError, 'outside'):
            selector.select_backend(self.project, 'fusion', routing_decision=forged,
                                    expected_selection=None, expected_routing_policy=policy)
        self.assertFalse((self.project / '.codex/config.toml').exists())

    def test_modified_decision_rejected_even_for_allowed_backend(self):
        policy = router.set_auto(self.project, ['cadquery'])['policy']
        decision = router.plan(self.project, ['box'], [], [])['decision']
        decision['verification']['required_checks'] = ['fatigue']
        with self.assertRaisesRegex(selector.SelectionError, 'modified'):
            selector.select_backend(self.project, 'cadquery', routing_decision=decision,
                                    expected_selection=None, expected_routing_policy=policy,
                                    routing_request={'mode': 'auto', 'required_operations': ['box']})
        self.assertIsNone(selector.read_selection(self.project))

    def test_freecad_stopping_between_plan_and_activation_blocks_write(self):
        router.set_auto(self.project, ['freecad'])
        probe = {'backend': 'freecad', 'operations': ['shell'], 'installed': True,
                 'ready': True, 'evidence': 'isolated shell test', 'cost': 'free'}
        observations = [{'installed': True, 'ready': True},
                        {'installed': True, 'ready': True},
                        {'installed': True, 'ready': False}]
        with patch.object(selector, 'inspect_freecad_kit', side_effect=observations):
            with self.assertRaisesRegex(selector.SelectionError, 'stopped'):
                router.plan(self.project, ['shell'], [], [probe], kit=self.project, activate=True)
        self.assertIsNone(selector.read_selection(self.project))
        self.assertFalse((self.project / '.codex/config.toml').exists())


if __name__ == '__main__':
    unittest.main()
