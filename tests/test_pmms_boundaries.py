"""Protect existing files before dispatching destructive server export operations."""
from pathlib import Path
import json
import sys
import tempfile
import unittest
from unittest.mock import Mock,patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'outputs/MeQLab_Local_Integration'))
from pmms_client import PmmsClient,PmmsError

class ExportBoundaries(unittest.TestCase):
    def setUp(self):
        temp_root=Path(__file__).resolve().parents[1]/'.cache/tests'
        temp_root.mkdir(parents=True,exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=temp_root)
        self.root=Path(self.temp.name)
        config=self.root/'config.json'
        config.write_text('{}')
        self.client=PmmsClient(config,self.root/'run/session',export_root=self.root/'run')
        self.client.initialized=True
        self.client.request=Mock(return_value={'content':[{'type':'text','text':'ok'}]})
    def tearDown(self):self.temp.cleanup()
    def test_rejects_outside_and_parent_without_server_call(self):
        for path in [self.root,self.root/'other',self.root/'run',self.root/'run/session/../../other']:
            with self.assertRaises(PmmsError):self.client.call_tool('save_sim_result',{'path':str(path)})
        self.client.request.assert_not_called()
    def test_existing_export_is_preserved(self):
        path=self.root/'run/existing'
        path.mkdir()
        sentinel=path/'do-not-delete.txt'
        sentinel.write_text('existing result')
        with self.assertRaises(PmmsError):self.client.call_tool('save_sim_result',{'path':str(path)})
        self.assertEqual(sentinel.read_text(),'existing result')
        self.client.request.assert_not_called()
    def test_new_export_in_explicit_run_root_is_sent(self):
        self.client.call_tool('save_sim_result',{'path':str(self.root/'run/new-export')})
        self.client.request.assert_called_once()
        self.assertEqual(self.client.tool_successes,1)
    def test_business_error_text_is_failure_even_without_is_error(self):
        self.client.request.return_value={'isError':False,'content':[{'type':'text','text':'错误：invalid model'}]}
        with self.assertRaises(PmmsError):self.client.call_tool('get_param',{})
        self.assertEqual(self.client.tool_successes,0)
    def test_missing_license_stops_before_launch(self):
        with patch.dict('os.environ',{},clear=True), patch('pmms_client.subprocess.Popen') as launch:
            with self.assertRaises(PmmsError):self.client.start()
            launch.assert_not_called()
    def test_environment_license_reaches_child_without_being_logged(self):
        self.client.config.update(runtime_root=str(self.root/'runtime'),pmms_path='pmms.exe',
            meqlab_path='meqlab.exe',feature='prim|rf_main|pnano',project_path=str(self.root/'project'))
        with patch.dict('os.environ',{'PRIMARIUS_LICENSE_FILE':'TEST_ONLY'},clear=True), patch('pmms_client.subprocess.Popen',side_effect=RuntimeError('launch intercepted')) as launch:
            with self.assertRaisesRegex(RuntimeError,'launch intercepted'):self.client.start()
            self.assertEqual(launch.call_args.kwargs['env']['PRIMARIUS_LICENSE_FILE'],'TEST_ONLY')
            self.assertNotIn('TEST_ONLY',self.client.events.read_text(encoding='utf-8'))

if __name__=='__main__':unittest.main()
