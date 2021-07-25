import argparse
import base64
import copy
import croniter
import datetime
from email.message import EmailMessage
from enum import Enum
import json
import logging
import os
import requests
import signal
import smtplib
import subprocess
import threading
import time
import traceback
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
        self._current_date = datetime.datetime.now().strftime('%Y%m%d')
        self._last_cron_check = datetime.datetime.now() - datetime.timedelta(seconds=60)
        self._ledger_lock = threading.Lock()
        self._config_override = config_overrides
        self.reload_config(None)

    def _run_job_in_separate_process(self, smqc, FC_target_id, job_name, cwd, run_cmd, log_filename,
                                     success_email_recipients, failure_email_recipients,
                                     success_slack_webhook, failure_slack_webhook):
        # TODO: Change to process and track PIDs in self._job_pids
        def threadworker_run_job():
            logger = logging.getLogger(f"{job_name}.{datetime.datetime.now().strftime('%Y%m%d')}")
            logger.setLevel(logging.INFO)

            file_handler = logging.FileHandler(filename=log_filename)
            file_handler.setFormatter(logging.Formatter('%(asctime)s %(message)s'))
            logger.addHandler(file_handler)

            try:
                logger.info('')
                logger.info('')
                logger.info('FlowController Starting Job')
                logger.info('')
                logger.info('')

                if run_cmd is None:
                    smqc.send_message(smqc.construct_msg('change_job_state', FC_target_id,
                                                         {'job_name': job_name, 'new_state': 'FAILURE',
                                                          'reason': 'missing run_cmd'}))
                    self._send_email(subject=f'FAILED {job_name}', body='Missing run_cmd',
                                     recipients=failure_email_recipients)
                    self._send_slack(text=f'FAILED {job_name}', webhook_url=failure_slack_webhook)
                    return
                try:
                    # set the current working directory to the directory of the cfg file
                    proc = subprocess.Popen(run_cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, shell=True)

                    job_output = b''
                    while True:
                        output = proc.stdout.readline()
                        if len(output) == 0 and proc.poll() is not None:
                            break
                        if output:
                            job_output += output + b'\n'
                            logger.info(output.strip().decode())
                            logger.handlers[0].flush()
                            smqc.send_message(smqc.construct_msg('job_log_changed', '*', {'job_name': job_name}))
                    job_output = job_output.decode()

                    rc = proc.poll()
                    if rc == 0:
                        smqc.send_message(smqc.construct_msg('change_job_state', FC_target_id,
                                                             {'job_name': job_name, 'new_state': 'SUCCESS', 'reason': 'Job Completed'}))

                        # update cron time
                        j = self._cfg['jobs'][job_name]
                        if 'cron' in j:
                            self._update_next_cron_fire_time(job_name, datetime.datetime.now())

                        self._send_email(subject=f'SUCCEEDED {job_name}', body=job_output,
                                         recipients=success_email_recipients)
                        self._send_slack(text=f'SUCCEEDED {job_name}', webhook_url=success_slack_webhook)
                    else:
                        smqc.send_message(smqc.construct_msg('change_job_state', FC_target_id,
                                                             {'job_name': job_name, 'new_state': 'FAILURE', 'reason': 'Job Completed'}))
                        self._send_email(subject=f'FAILED {job_name}', body=job_output,
                                         recipients=failure_email_recipients)
                        self._send_slack(text=f'FAILED {job_name}', webhook_url=failure_slack_webhook)
                except Exception as _:
                    logger.error(traceback.format_exc())
                    smqc.send_message(smqc.construct_msg('change_job_state', FC_target_id,
                                                         {'job_name': job_name, 'new_state': 'FAILURE', 'reason': 'Job Error'}))
                    self._send_email(subject=f'FAILED {job_name}', body=job_output,
                                     recipients=failure_email_recipients)
                    self._send_slack(text=f'FAILED {job_name}', webhook_url=failure_slack_webhook)
            finally:
                file_handler.close()
                logger.removeHandler(file_handler)

        t = threading.Thread(target=threadworker_run_job, args=())
        t.start()

    def _send_email(self, subject, body, recipients):
        try:
            logging.info(f'SENDING EMAIL! {subject} {recipients} {body}')
            if recipients is None or recipients.strip() == '':
                logging.info('NOT SEND SENDING EMAIL!')
                return
            msg = EmailMessage()
            msg.set_content(body)

            msg['Subject'] = subject
            msg['From'] = self._cfg.get('email_sender', '')
            msg['To'] = recipients
            s = smtplib.SMTP('localhost')
            s.send_message(msg)
            s.quit()
        except Exception as e:
            logging.exception(e)

    def _send_slack(self, text, webhook_url):
        try:
            slack_data = {'text': text}

            response = requests.post(
                webhook_url, data=json.dumps(slack_data),
                headers={'Content-Type': 'application/json'}
            )
            if response.status_code != 200:
                logging.error(response.status_code)
                logging.error(response.text)
        except Exception as e:
            logging.exception(e)

    def _update_next_cron_fire_time(self, job_name, base):
        cron_iter = croniter.croniter(self._cfg['jobs'][job_name]['cron'], base)
        self._cfg['jobs'][job_name]['next_cron_fire_time'] = cron_iter.get_next(datetime.datetime)

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
        # check for a new day
        if self._current_date != datetime.datetime.now().strftime('%Y%m%d'):
            self._current_date = datetime.datetime.now().strftime('%Y%m%d')
            self.reload_config(smqc)

        # check if cron cooldown is passed
        process_cron = False
        cron_time = datetime.datetime.now()
        if cron_time > self._last_cron_check + datetime.timedelta(seconds=60):
            self._last_cron_check = cron_time
            process_cron = True

        # loop through all the jobs
        jobs = self._cfg['jobs']
        for jn, j in jobs.items():
            # skip any nodes that are not IDLE or do not have depends
            if j['state'] != JobState.IDLE:
                continue

            # check if any jobs have all of their dependencies met, if so, change to pending
            if len(j.get('depends', [])) != 0:
                # check if all dependencies are met
                if all([(djn in jobs) and (jobs[djn]['state'] == JobState.SUCCESS) for djn in j['depends']]):
                    self.change_job_state(smqc, jn, JobState.PENDING, 'Dependencies Ready')

            # process cron jobs
            if process_cron:
                if 'next_cron_fire_time' in j:
                    if cron_time > j['next_cron_fire_time']:
                        self._update_next_cron_fire_time(jn, cron_time)
                        self.change_job_state(smqc, jn, JobState.PENDING, 'cron fire time')

        # execute any pending jobs
        for jn, j in jobs.items():
            if j['state'] == JobState.PENDING:
                self.change_job_state(smqc, jn, JobState.RUNNING, 'pending')
                self._run_job_in_separate_process(
                    smqc=smqc, FC_target_id=self.get_config_prop('uid'), job_name=jn,
                    cwd=os.path.join(os.path.dirname(os.path.abspath(self._config_filename))),
                    run_cmd=self._cfg['jobs'][jn].get('run_cmd', None),
                    log_filename=self.get_log_filename(jn),
                    success_email_recipients=self._cfg['jobs'][jn].get('success_email_recipients', None),
                    failure_email_recipients=self._cfg['jobs'][jn].get('failure_email_recipients', None),
                    success_slack_webhook=self._cfg['jobs'][jn].get('success_slack_webhook', None),
                    failure_slack_webhook=self._cfg['jobs'][jn].get('failure_slack_webhook', None))

    def reload_config(self, smqc):
        """ reload the config and broadcast a config_changed message """
        # read the config file
        self._cfg = FlowController_util.read_cfg_file(self._config_filename)

        for k, v in self._config_override.items():
            if v is not None:
                logging.info(f'Overriding {k} in config.  Old value was {self._cfg.get(k, "?")}, new value is {v}')
                self._cfg[k] = v

        # set all job states to idle, setup the next cron fire time, and inject email addresses
        cron_base = datetime.datetime.now()
        for jn, j in self._cfg['jobs'].items():
            j['state'] = JobState.IDLE
            if 'cron' in j:
                self._update_next_cron_fire_time(jn, cron_base)
            j['success_email_recipients'] = j.get('success_email_recipients', self._cfg['success_email_recipients'])
            j['failure_email_recipients'] = j.get('failure_email_recipients', self._cfg['failure_email_recipients'])
            j['success_slack_webhook'] = j.get('success_slack_webhook', self._cfg['success_slack_webhook'])
            j['failure_slack_webhook'] = j.get('failure_slack_webhook', self._cfg['failure_slack_webhook'])

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
        parser.add_argument('--override_email_sender', help='override the email_sender value in the config file')
        parser.add_argument('--override_success_email_recipients',
                            help='override the success_email_recipients value in the config file')
        parser.add_argument('--override_failure_email_recipients',
                            help='override the failure_email_recipients value in the config file')
        parser.add_argument('--override_success_slack_webhook',
                            help='override the success_slack_webhook value in the config file')
        parser.add_argument('--override_failure_slack_webhook',
                            help='override the failure_slack_webhook value in the config file')

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
