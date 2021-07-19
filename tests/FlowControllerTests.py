""" unit tests for Flow Controller """
import os
import threading
import time
import unittest
from FlowController.FlowController import FlowController, run
from SimpleMessageQueue.SMQ_Server import SMQ_Server


class TestFlowController(unittest.TestCase):
    """ Test Class for Flow Controller """
    FLOWCONTROLLER = None
    FLOWCONTROLLER_CONFIG_FILENAME = os.path.join(os.path.dirname(__file__),
                                                  '../sample_cfgs_and_jobs/simple_example.py.cfg')
    SMQ_SERVER = None
    SMQ_SERVER_PORT = None

    @classmethod
    def _start_smq_server(cls):
        """ thread worker to start smq server """
        print('Starting SMQ Server')
        cls.SMQ_SERVER = SMQ_Server('localhost', 0)
        cls.SMQ_SERVER.start()

    @classmethod
    def _start_flow_controller(cls):
        """ thread worker to start flow controller """
        print('Starting Flow Controller')
        cls.FLOWCONTROLLER = FlowController(
            config_filename=cls.FLOWCONTROLLER_CONFIG_FILENAME,
            config_overrides={'smq_server': 'http://localhost:' + str(cls.SMQ_SERVER_PORT),
                              'ledger_dir': os.path.join(os.path.dirname(__file__), 'logs'),
                              'job_logs_dir': os.path.join(os.path.dirname(__file__), 'logs')})
        cls.FLOWCONTROLLER.start()

    @classmethod
    def setUpClass(cls):
        """ setUpClass """
        # clean up directory
        log_dir = os.path.join(os.path.dirname(__file__), 'logs')
        if os.path.exists(log_dir):
            for f in os.listdir(log_dir):
                if os.path.isfile(os.path.join(log_dir, f)):
                    os.remove(os.path.join(log_dir, f))

        # start the SMQ Server
        t = threading.Thread(target=cls._start_smq_server, daemon=True)
        t.start()
        for _ in range(0, 15):
            time.sleep(0.2)
            try:
                cls.SMQ_SERVER_PORT = cls.SMQ_SERVER._rpc_server.server_address[1]
                break
            except Exception as _:
                print('Waiting... SMQ Server not started yet')
        print(f'SMQ Server started on port {cls.SMQ_SERVER_PORT}')

        # start the FlowController
        t2 = threading.Thread(target=cls._start_flow_controller, daemon=True)
        t2.start()
        time.sleep(2)

    @classmethod
    def tearDownClass(cls):
        """ tearDownClass """
        # stop the FlowController
        print('Stopping Flow Controller')
        cls.FLOWCONTROLLER.stop()
        time.sleep(2)

        # stop the SMQ Server
        print('Stopping SMQ Server')
        cls.SMQ_SERVER.shutdown()
        time.sleep(2)

    def _run(self, args):
        """ run functino helper """
        args['config'] = args.get('config', TestFlowController.FLOWCONTROLLER_CONFIG_FILENAME)
        args['override_smq_server'] = args.get('override_smq_server',
                                               'http://localhost:' + str(TestFlowController.SMQ_SERVER_PORT))
        args['override_ledger_dir'] = args.get('override_ledger_dir',
                                               os.path.join(os.path.dirname(__file__), 'logs'))
        args['override_job_logs_dir'] = args.get('override_job_logs_dir',
                                                 os.path.join(os.path.dirname(__file__), 'logs'))
        return run(args)

    def test_change_job_state(self):
        """ test change job state action """
        response_payload = self._run({'action': 'change_job_state', 'job_name': 'test_dep_cron_job2',
                                      'new_state': 'FAILURE'})
        assert(response_payload['retval'] == 0)
        time.sleep(1)
        output = self._run({'status': True})
        assert(output.split('\n')[2].partition(':')[2] == ' FAILURE')

    def test_dependent_jobs(self):
        """ test dependenat jobs """
        response_payload = self._run({'action': 'change_job_state', 'job_name': 'test_cron_job_5',
                                      'new_state': 'IDLE'})
        assert(response_payload['retval'] == 0)
        response_payload = self._run({'action': 'change_job_state', 'job_name': 'test_dep_cron_job',
                                      'new_state': 'IDLE'})
        assert(response_payload['retval'] == 0)
        response_payload = self._run({'action': 'change_job_state', 'job_name': 'test_dep_cron_job2',
                                      'new_state': 'IDLE'})
        assert(response_payload['retval'] == 0)
        response_payload = self._run({'action': 'change_job_state', 'job_name': 'test_multiple_deps',
                                      'new_state': 'IDLE'})
        assert(response_payload['retval'] == 0)
        response_payload = self._run({'action': 'trigger_job', 'job_name': 'test_cron_job_5',
                                      'reason': 'unit test'})
        assert(response_payload['retval'] == 0)
        time.sleep(2)
        output = self._run({'status': True})
        assert(output.split('\n')[0].partition(':')[2] == ' SUCCESS')
        assert(output.split('\n')[1].partition(':')[2] == ' SUCCESS')
        assert(output.split('\n')[2].partition(':')[2] == ' SUCCESS')
        assert(output.split('\n')[3].partition(':')[2] == ' SUCCESS')

    def test_list(self):
        """ test list output """
        assert(self._run({'list': True}).startswith('simple_example\t{'))

    def test_ping(self):
        """ test oing action """
        response_payload = self._run({'action': 'ping'})
        assert(response_payload['retval'] == 0)

    def test_reload_config(self):
        """ test reload config action """
        response_payload = self._run({'action': 'reload_config'})
        assert(response_payload['retval'] == 0)

    def test_request_config(self):
        """ test request config action """
        response_payload = self._run({'action': 'request_config'})
        assert(response_payload['retval'] == 0)
        assert('config' in response_payload)

    def test_request_icon(self):
        """ test request icon action """
        response_payload = self._run({'action': 'request_icon'})
        assert(response_payload['retval'] == 0)
        assert('icon' in response_payload)

    def test_request_log_chunk(self):
        """ test request log chunk action """
        response_payload = self._run({'action': 'trigger_job', 'job_name': 'test_dep_cron_job2',
                                      'reason': 'unit test'})
        assert(response_payload['retval'] == 0)
        time.sleep(1)
        response_payload = self._run({'action': 'request_log_chunk', 'job_name': 'test_dep_cron_job2',
                                      'log_range': ''})
        assert(response_payload['retval'] == 0)
        assert('log' in response_payload)

    def test_status(self):
        """ test status output """
        output = self._run({'status': True})
        assert(output.split('\n')[0].startswith('test_cron_job_5:'))
        assert(output.split('\n')[1].startswith('test_dep_cron_job:'))
        assert(output.split('\n')[2].startswith('test_dep_cron_job2:'))
        assert(output.split('\n')[3].startswith('test_multiple_deps:'))

    def test_trigger_job(self):
        """ test trigger job action """
        response_payload = self._run({'action': 'trigger_job', 'job_name': 'test_dep_cron_job2',
                                      'reason': 'unit test'})
        assert(response_payload['retval'] == 0)
        time.sleep(1)
        output = self._run({'status': True})
        assert(output.split('\n')[2].partition(':')[2] == ' SUCCESS')


if __name__ == '__main__':
    unittest.main()
