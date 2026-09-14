import copy
import unittest

from infra.prepare_training_vm import LAB, VM, ZONE, MACHINES, create_command, verify_training_vm


class TrainingInfraTest(unittest.TestCase):
    def test_bounded_lab_command(self):
        cmd = create_command()
        self.assertEqual(cmd[:4], LAB.gcloud)
        for flag in ('--no-service-account', '--no-scopes', '--max-run-duration=12h',
                     '--instance-termination-action=STOP', '--no-restart-on-failure'):
            self.assertIn(flag, cmd)
        self.assertNotIn('semantic-reader-pilot', cmd)

    def test_verify_rejects_identity_credentials_and_unbounded_vm(self):
        vm = {'selfLink': f'https://www.googleapis.com/compute/v1/projects/{LAB.project}/zones/{ZONE}/instances/{VM}',
              'machineType': f"projects/{LAB.project}/zones/{ZONE}/machineTypes/{MACHINES['a100-80gb']}",
              'scheduling': {'maxRunDuration': {'seconds': '43200'},
                             'instanceTerminationAction': 'STOP', 'automaticRestart': False}}
        verify_training_vm(vm)
        for change in ({'selfLink': 'another-project'}, {'serviceAccounts': [{'email': 'other'}]},
                       {'scheduling': {}}, {'machineType': 'large'}):
            changed = copy.deepcopy(vm)
            changed.update(change)
            with self.assertRaises(RuntimeError):
                verify_training_vm(changed)
