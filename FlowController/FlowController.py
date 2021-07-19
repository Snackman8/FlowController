import argparse
import base64
import copy
import datetime
from enum import Enum
import logging
import os
import signal
import threading
import time
import uuid
from SimpleMessageQueue.SMQ_Client import SMQ_Client
try:
    import FlowController.FlowController_util as FlowController_util
except:
    import FlowController_util


JobState = Enum('JobState', 'IDLE PENDING RUNNING SUCCESS FAILURE')


class JobManager():
    def __init__(self, config_filename, config_overrides={}):
        self._cfg = None
        self._config_filename = config_filename
        self._ledger_lock = threading.Lock()
        self._config_override = config_overrides
        self.reload_config(None)

    def change_job_state(self, smqc, job_name, new_state, reason):
        # change the job state
        try:
            self._ledger_lock.acquire()
            FlowController_util.FlowControllerLedger.append(self._cfg['ledger_dir'], self._cfg['uid'], job_name, new_state.name, reason)
            self._cfg['jobs'][job_name]['state'] = new_state
        finally:
            self._ledger_lock.release()

        # broadcast config_changed
        smqc.send_message(smqc.construct_msg('job_state_changed', '*', {'job_name': job_name, 'new_state': new_state.name}))

        # success
        return {'retval': 0}

    def get_config_prop(self, prop):
        """ read a property from the config file.

            Args:
                prop - available props: title, uid, logo_filename, jobs

            Returns:
                the value of the prop
        """
        return self._cfg[prop]

    def get_config_snapshot(self, _smqc):
        # xmlrpc cannot marshal enums, so convert to string
        d = copy.deepcopy(self._cfg)
        for jn in d['jobs']:
            d['jobs'][jn]['state'] = d['jobs'][jn]['state'].name
        return {'retval': 0, 'config': d}

    def get_icon(self, _smqc):
        icon_filename = os.path.join(os.path.dirname(self._config_filename), self._cfg['logo_filename'])
        with open(icon_filename, 'rb') as f:
            return {'retval': 0, 'icon': base64.b64encode(f.read()).decode("ascii")}

    def get_log_chunk(self, _smqc, job_name, log_range):
        filename = self.get_log_filename(job_name)
        if os.path.exists(filename):
            f = open(filename, 'r')
            s = f.read()
            f.close()
            s = filename + "\n-----\n" + s
            s = s[slice(*[int(x) if x else None for x in log_range.split(':')])]
        else:
            s = f'This job may not have run for today yet.</span>\n\nlog file at {filename} does not exist.'
        return {'retval': 0, 'log': s}

    def get_log_filename(self, job_name, date=None):
        if date is None:
            date = datetime.datetime.now()
        return os.path.abspath(os.path.join(
            self._cfg['job_logs_dir'],
            f"{self._cfg['uid']}.{job_name}.{datetime.datetime.now().strftime('%Y%m%d')}.log"))

    def process_jobs(self, smqc):
        # check if any jobs have all of their dependencies met, if so, change to pending
        jobs = self._cfg['jobs']
        for jn, j in jobs.items():
            # skip any nodes that are not IDLE or do not have depends
            if len(j.get('depends', [])) == 0 or j['state'] != JobState.IDLE:
                continue

            # check if all dependencies are met
            if all([(djn in jobs) and (jobs[djn]['state'] == JobState.SUCCESS) for djn in j['depends']]):
                self.change_job_state(smqc, jn, JobState.PENDING, 'Dependencies Ready')

        # change any triggered cron jobs to pending

        # execute any pending jobs
        for jn, j in jobs.items():
            if j['state'] == JobState.PENDING:
                self.change_job_state(smqc, jn, JobState.RUNNING, 'pending')
                FlowController_util.run_job_in_separate_process(
                    smqc=smqc, FC_target_id=self.get_config_prop('uid'), job_name=jn,
                    cwd=os.path.join(os.path.dirname(os.path.abspath(self._config_filename))),
                    run_cmd=self._cfg['jobs'][jn].get('run_cmd', None),
                    log_filename=self.get_log_filename(jn))

    def reload_config(self, smqc):
        """ reload the config and broadcast a config_changed message """
        # read the config file
        self._cfg = FlowController_util.read_cfg_file(self._config_filename)

        for k, v in self._config_override.items():
            if v is not None:
                logging.info(f'Overriding {k} in config.  Old value was {self._cfg.get(k, "?")}, new value is {v}')
                self._cfg[k] = v

        # set all job states to idle
        for _, j in self._cfg['jobs'].items():
            j['state'] = JobState.IDLE

        # load the states from the ledger
        try:
            self._ledger_lock.acquire()
            df = FlowController_util.FlowControllerLedger.read(self._cfg['ledger_dir'], self._cfg['uid'])
            for _, r in df.iterrows():
                if r['job_name'] in self._cfg['jobs']:
                    self._cfg['jobs'][r['job_name']]['state'] = JobState[r['state']]
        finally:
            self._ledger_lock.release()

        # broadcast config_changed
        if smqc is not None:
            smqc.send_message(smqc.construct_msg('config_changed', '*', {}))

        # success
        return {'retval': 0}

    def trigger_job(self, smqc, job_name, reason):
        """ trigger a job

            Args:
                job_name - name of the job to trigger
        """
        self.change_job_state(smqc, job_name, JobState.PENDING, reason)
        return {'retval': 0}


class FlowController():
    def __init__(self, config_filename, config_overrides={}):
        """ init """
        self._shutdown = False
        self._job_manager = JobManager(config_filename, config_overrides)

    def _build_smq_client(self):
        client_uid = self.get_client_id()
        classifications = ['FlowController', client_uid]
        pub_list = ['change_job_state', 'config_changed', 'job_log_changed', 'job_state_changed']
        sub_list = ['change_job_state', 'ping', 'reload_config', 'request_config', 'request_icon', 'request_log_chunk',
                    'trigger_job']
        return SMQ_Client(self._job_manager.get_config_prop('smq_server'), client_uid, client_uid, classifications,
                          pub_list, sub_list, tag={'title': self._job_manager.get_config_prop('title')})

    def build_smq_terminal_client(self):
        client_uid = 'FC_TERM_' + uuid.uuid4().hex
        classifications = ['FlowController_Terminal']
        pub_list = ['change_job_state', 'ping', 'reload_config', 'request_config', 'request_icon', 'request_log_chunk',
                    'trigger_job']
        sub_list = []
        return SMQ_Client(self._job_manager.get_config_prop('smq_server'), client_uid, client_uid, classifications,
                          pub_list, sub_list, tag={'title': self._job_manager.get_config_prop('title')})

    def get_client_id(self):
        return self._job_manager.get_config_prop('uid')

    def _main_loop(self, smqc):
        try:
            signal.signal(signal.SIGTERM, lambda _a, _b: self.stop())
            signal.signal(signal.SIGINT, lambda _a, _b: self.stop())
        except ValueError as e:
            logging.info(e)

        while not self._shutdown:
            self._job_manager.process_jobs(smqc)
            time.sleep(0.1)

        smqc.stop()

    def list(self):
        client = self._build_smq_client()
        all_client_info = client.get_info_for_all_clients()
        return all_client_info

    def start(self):
        """ start the flow controller """
        client = self.build_smq_terminal_client()
        all_client_info = client.get_info_for_all_clients()

        # verify this config_id is not already running
        if self.get_client_id() in all_client_info.keys():
            # send a ping to make sure
            if client.is_alive(self.get_client_id()):
                raise Exception(f'A Flow Controller config with uid of {self.get_client_id()} is already running')

        # start the SMQ_Client
        client = self._build_smq_client()
        client.add_message_handler('change_job_state', lambda msg, smqc:
                                   self._job_manager.change_job_state(smqc, msg['payload']['job_name'],
                                                                      JobState[msg['payload']['new_state']],
                                                                      msg['payload']['reason']))
        client.add_message_handler('ping', lambda _msg, _smqc: {'retval': 0})
        client.add_message_handler('reload_config', lambda _msg, smqc: self._job_manager.reload_config(smqc))
        client.add_message_handler('request_config', lambda _msg, smqc: self._job_manager.get_config_snapshot(smqc))
        client.add_message_handler('request_icon', lambda _msg, smqc: self._job_manager.get_icon(smqc))
        client.add_message_handler('request_log_chunk', lambda msg, smqc:
                                   self._job_manager.get_log_chunk(smqc, msg['payload']['job_name'],
                                                                   msg['payload']['range']))
        client.add_message_handler('trigger_job', lambda msg, smqc:
                                   self._job_manager.trigger_job(smqc, msg['payload']['job_name'],
                                                                 msg['payload']['reason']))
        client.start()

        # start the main loop
        self._main_loop(client)

    def stop(self):
        self._shutdown = True


# --------------------------------------------------
#    Main
# --------------------------------------------------
def run(args):
    """ run """
    client = None
    try:
        overrides = {}
        for k, v in args.items():
            if k.startswith('override_'):
                overrides[k[9:]] = v

        FC = FlowController(args['config'], overrides)
        if not os.path.exists(FC._job_manager.get_config_prop('ledger_dir')):
            os.makedirs(FC._job_manager.get_config_prop('ledger_dir'))
        if not os.path.exists(FC._job_manager.get_config_prop('job_logs_dir')):
            os.makedirs(FC._job_manager.get_config_prop('job_logs_dir'))

        # start the server if requested
        if args.get('start', False):
            return FC.start()

        # build a terminal client
        client = FC.build_smq_terminal_client()
        client.start()

        # handle list
        if args.get('list', False):
            # list the running flow controllers
            all_client_info = client.get_info_for_all_clients()
            s = ''
            for k, v in all_client_info.items():
                s += f'{k}\t{v}\n'
                print(f'{k}\t{v}')
            return s

        # handle status
        if args.get('status', False):
            msg = client.construct_msg('request_config', FC.get_client_id(), {})
            response_payload = client.send_message(msg, wait=5)
            s = ''
            for j in response_payload['config']['jobs'].values():
                s += f'{j["name"]}: {j["state"]}\n'
                print(f'{j["name"]}: {j["state"]}')
            return s

        # handle actions
        if args.get('action', None) is not None:
            if args['action'] == 'change_job_state':
                payload = {'job_name': args['job_name'], 'new_state': args['new_state'], 'reason': 'terminal'}
            if args['action'] in ('ping', 'reload_config', 'request_config', 'request_icon'):
                payload = {}
            if args['action'] == 'request_log_chunk':
                payload = {'job_name': args['job_name'], 'range': args['log_range']}
            if args['action'] == 'trigger_job':
                payload = {'job_name': args['job_name'], 'reason': 'terminal'}

            msg = client.construct_msg(args['action'], FC.get_client_id(), payload)
            response_payload = client.send_message(msg, wait=5)
            return response_payload
    except ConnectionRefusedError:
        logging.error(f'SMQ Server at {FC._job_manager.get_config_prop("smq_server")} is refusing connection')
    finally:
        if client is not None:
            client.stop()


if __name__ == "__main__":
    try:
        # parse the arguments
        parser = argparse.ArgumentParser(description='Flow Controller')
        parser.add_argument('--config', required=True, help='filename of config file to use, i.e. cfg_test.py')
        parser.add_argument('--start', action='store_true', help='start the Flow Controller for the config')
        parser.add_argument('--status', action='store_true', help='show the status of jobs in the config')
        parser.add_argument('--list', action='store_true', help='list running Flow Controllers on the same ' +
                                                                'bus as the config')
        parser.add_argument('--action', choices=['change_job_state', 'ping', 'reload_config', 'request_config',
                                                 'request_icon', 'request_log_chunk', 'trigger_job'],
                                                 help='perform an action on the Flow Controller running the config')
        parser.add_argument('--job_name', help='job name to perform the action on')
        parser.add_argument('--new_state', help='new state of the job, only used with the change_job_state ' +
                                                'action')
        parser.add_argument('--log_range', help='character range of the log to return, i.e. 0:1000 for the ' +
                                                'first 1000 characters.  only used with the request_log_chunk ' +
                                                'action', default='')
        parser.add_argument('--logging_level', default='ERROR')
        parser.add_argument('--override_smq_server', help='override the sqm_server value in the config file')
        parser.add_argument('--override_ledger_dir', help='override the ledger_dir value in the config file')
        parser.add_argument('--override_job_logs_dir', help='override the job_logs_dir value in the config file')
        args = parser.parse_args()

        # setup logging
        logging.basicConfig(level=logging.getLevelName(args.logging_level),
                            format='%(asctime)s %(levelname)s %(threadName)s %(message)s')
        logging.info('Starting ', vars(args))

        # run
        run(vars(args))
    except Exception as e:
        logging.exception('Exception')
        raise(e)
