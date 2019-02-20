import unittest
import yaml

from mock import Mock, MagicMock, patch

from ansible.playbook.task import Task
from ansible.parsing.dataloader import DataLoader

from action_plugins.conga_facts import ActionModule

HOST_VARS = {'localhost': {'conga_basedir': 'basedir'}}
TASK_VARS = {'inventory_hostname': 'hostname',
             'conga_target_path': 'target_path',
             'conga_environment': 'environment',
             'conga_node': 'node',
             'hostvars': HOST_VARS}

class MockModule(ActionModule):

    def __init__(self, task):
        self.play_context = Mock()
        self.connection = Mock()
        self.connection.shell = 'sh'
        super(ActionModule, self).__init__(task, self.connection, self.play_context, None, None, None)
        self._task_vars = None

    def run(self, task_vars=TASK_VARS):
        with open('tests/fixtures/model.yaml') as f:
            mock_loader = MagicMock(DataLoader)
            mock_loader.load.return_value = yaml.load(f.read())
            self._loader = mock_loader

        with patch('action_plugins.conga_facts.open') as mock_open:
            mock_open.return_value = MagicMock(spec=file)
            result = super(MockModule, self).run(None, task_vars)
            mock_open.assert_called_once()
            return result

    def get_facts(self, task_vars=TASK_VARS):
        result = self.run(task_vars)
        facts = result.get("ansible_facts")
        if facts:
            return facts
        raise Exception(result)

class MockRole:

    def __init__(self, name):
        self._role_name = name

class TestCongaFactsPlugin(unittest.TestCase):

    def test_match_conga_role(self):
        task = Mock(Task)

        role_db = {'role': 'db'}
        role_cms = {'role': 'cms'}
        roles = [role_db, role_cms]

        conga_facts = MockModule(task)

        # Match exact name
        self.assertEqual(conga_facts._match_conga_role(roles, "db", None), role_db)
        # Match name with prefix
        self.assertEqual(conga_facts._match_conga_role(roles, "ops.conga_db", None), role_db)
        # No match
        self.assertIsNone(conga_facts._match_conga_role(roles, "web", None))

    def test_parent_role_no_parent(self):
        task = Mock(Task)
        task._parent = None
        self.assertIsNone(MockModule(task).parent_role)

    def test_parent_role_empty_parent(self):
        task = Mock(Task)
        task._parent = dict()
        self.assertIsNone(MockModule(task).parent_role)

    def test_parent_role_with_parent(self):
        task = Mock(Task)
        task._parent = Task(None, MockRole("parent_role"), None)
        self.assertEqual(MockModule(task).parent_role, "parent_role")

    def test_conga_config_path_custom(self):
        task = Task(None, MockRole('db'), None)
        facts = MockModule(task).get_facts()
        self.assertEqual("basedir/target_path/environment/node", facts.get('conga_config_path'))
        self.assertEqual("basedir", facts.get('conga_basedir'))
        self.assertDictEqual({"path": "/opt/db"}, facts.get('conga_config'))
        self.assertEqual([{'tenant': 'tenant1'}], facts.get('conga_tenants'))

    def test_conga_config_path_default(self):
        task = Task(None, MockRole('db'), None)
        task_vars = dict(TASK_VARS)
        task_vars.pop("conga_target_path")
        task_vars.pop("conga_node")
        facts = MockModule(task).get_facts(task_vars)
        self.assertEqual("basedir/target/configuration/environment/hostname", facts.get('conga_config_path'))

    def test_conga_variants_single(self):
        task = Task(None, MockRole('db'), None)
        facts = MockModule(task).get_facts()
        self.assertEqual("primary", facts.get('conga_variant'))
        self.assertEqual(['primary'], facts.get('conga_variants'))

    def test_conga_variants_none(self):
        task = Task(None, MockRole('cms'), None)
        facts = MockModule(task).get_facts()
        self.assertIsNone(facts.get('conga_variant'))
        self.assertEqual([], facts.get('conga_variants'))

    def test_conga_role_source_mapping(self):
        task = Task(None, MockRole('conga_facts'), None)
        task_vars = dict(TASK_VARS)
        task_vars['conga_role_mapping'] = "cms"
        facts = MockModule(task).get_facts(task_vars)
        self.assertEqual("cms", facts.get('conga_role'))

    # TODO: When the role for an explicit mapping cannot be resolved we should fail in any case
    # Currently we proceed with the mapping in any case which is
    @unittest.expectedFailure
    def test_conga_role_source_mapping_invalid(self):
        task = Task(None, MockRole('db'), None)
        task_vars = dict(TASK_VARS)
        task_vars['conga_role_mapping'] = "web"
        result = MockModule(task).run()
        self.assertTrue(result.get('failed'))

    def test_conga_role_source_current(self):
        task = Task(None, MockRole('db'), None)
        facts = MockModule(task).get_facts()
        self.assertEqual("db", facts.get('conga_role'))

    def test_conga_role_source_current_with_prefix(self):
        task = Task(None, MockRole('ops.conga_db'), None)
        # TODO: Both of those should work
        # task = Task(None, MockRole('conga_db'), None)
        # task = Task(None, MockRole('ops.db'), None)
        facts = MockModule(task).get_facts()
        self.assertEqual("db", facts.get('conga_role'))

    @patch.object(Task, 'get_dep_chain')
    def test_conga_role_source_dependency(self, mock_method):
        mock_method.return_value = ["db", "cms", "web"]
        facts = MockModule(Task()).get_facts()
        mock_method.assert_called_once()
        self.assertEqual("db", facts.get('conga_role'))

    def test_conga_role_source_parent(self):
        task = Task()
        task._parent = Task(None, MockRole("cms"), None)
        facts = MockModule(task).get_facts()
        self.assertEqual("cms", facts.get('conga_role'))

    def test_conga_role_source_none(self):
        result = MockModule(Task()).run()
        self.assertTrue(result.get('failed'))

    def test_conga_role_source_unmatched(self):
        task = Task(None, MockRole("web"), None)
        result = MockModule(task).run()
        self.assertTrue(result.get('failed'))
