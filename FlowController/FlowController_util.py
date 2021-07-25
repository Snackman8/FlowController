import ast
import datetime
import logging
import os
import pandas as pd
import subprocess
import threading
import traceback


def read_cfg_file(cfg_filename):
    # execute the config to get the output
    proc = subprocess.Popen(['python3', cfg_filename], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    stdout, stderr = proc.communicate()
    if proc.returncode != 0:
        logging.error('Error interpeting config file')
        logging.error(stdout.decode())
        logging.error(stderr.decode())
        raise Exception('Error interpreting config file')
    cfg = ast.literal_eval(stdout.decode())

    cfg['jobs'] = {j['name']: j for j in cfg['jobs']}
    cfg['smq_server'] = f'http://{cfg["smq_server"]}'
    cfg['ledger_dir'] = os.path.join(os.path.dirname(os.path.abspath(cfg_filename)), cfg['ledger_dir'])
    cfg['job_logs_dir'] = os.path.join(os.path.dirname(os.path.abspath(cfg_filename)), cfg['job_logs_dir'])
    cfg['email_sender'] = cfg.get('email_sender', None)
    cfg['success_email_recipients'] = cfg.get('success_email_recipients', None)
    cfg['failure_email_recipients'] = cfg.get('failure_email_recipients', None)
    cfg['success_slack_webhook'] = cfg.get('success_slack_webhook', None)
    cfg['failure_slack_webhook'] = cfg.get('failure_slack_webhook', None)
    return cfg


# def run_job_in_separate_process(smqc, FC_target_id, job_name, cwd, run_cmd, log_filename):
#     # TODO: Change to process and track PIDs in self._job_pids
#     def threadworker_run_job(job_name):
#         logger = logging.getLogger(f"{job_name}.{datetime.datetime.now().strftime('%Y%m%d')}")
#         logger.setLevel(logging.INFO)
#         if not logger.handlers:
#             file_handler = logging.FileHandler(filename=log_filename)
#             file_handler.setFormatter(logging.Formatter('%(asctime)s %(message)s'))
#             logger.addHandler(file_handler)
# 
#         logger.info('')
#         logger.info('')
#         logger.info('FlowController Starting Job')
#         logger.info('')
#         logger.info('')
#         
#         if run_cmd is None:
#             smqc.send_message(smqc.construct_msg('change_job_state', FC_target_id,
#                                                  {'job_name': job_name, 'new_state': 'FAILURE',
#                                                   'reason': 'missing run_cmd'}))
#             return
#             
#         try:
#             # set the current working directory to the directory of the cfg file
#             proc = subprocess.Popen(run_cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, shell=True)
#                 
#             while True:
#                 output = proc.stdout.readline()
#                 if len(output) == 0 and proc.poll() is not None:
#                     break
#                 if output:
#                     logger.info(output.strip().decode())
#                     logger.handlers[0].flush()
#                     smqc.send_message(smqc.construct_msg('job_log_changed', FC_target_id, {'job_name': job_name}))
# 
#             rc = proc.poll()
#             if rc == 0:
#                 smqc.send_message(smqc.construct_msg('change_job_state', FC_target_id,
#                                                      {'job_name': job_name, 'new_state': 'SUCCESS', 'reason': 'Job Completed'}))
# 
# 
# 
#             else:
#                 smqc.send_message(smqc.construct_msg('change_job_state', FC_target_id,
#                                                      {'job_name': job_name, 'new_state': 'FAILURE', 'reason': 'Job Completed'}))
#         except:
#             logger.error(traceback.format_exc())
#             msg = smqc.construct_msg('change_job_state', FC_target_id,
#                                      {'job_name': job_name, 'new_state': 'FAILURE', 'reason': 'Job Error'})
# 
#     t = threading.Thread(target=threadworker_run_job, args=(job_name,))
#     t.start()


class FlowControllerLedger():
#     def __init__(self, ledger_dir, uid):
#         self._column_names = ['timestamp', 'job_name', 'state', 'reason']
#         self._ledger_dir = ledger_dir
#         self._uid = uid

    COLUMN_NAMES = ['timestamp', 'job_name', 'state', 'reason']

    @classmethod
    def _get_filename(cls, date, ledger_dir, ledger_uid):
        # sanity check
        datetime.datetime.strptime(date, '%Y%m%d')
        return os.path.join(ledger_dir, f'{ledger_uid}.{date}.ledger')

    @classmethod
    def append(cls, ledger_dir, ledger_uid, job_name, state, reason):
        # create a new file if it does not exist
        d = datetime.datetime.now()
        filename = cls._get_filename(d.strftime('%Y%m%d'), ledger_dir, ledger_uid)
        if not os.path.exists(filename):
            with open(filename, 'w') as f:
                f.write(','.join(FlowControllerLedger.COLUMN_NAMES) + '\n')

        # append to the file
        with open(filename, 'a') as f:
            timestamp = d.strftime("%Y-%m-%d %H:%M:%S")
            f.write(f"{timestamp},{job_name},{state},{reason}\n")

    @classmethod
    def read(cls, ledger_dir, ledger_uid, date=None):
        # default dataframe if file does not exist or is empty
        if date is None:
            date = datetime.datetime.now().strftime('%Y%m%d')

        df = pd.DataFrame(columns=FlowControllerLedger.COLUMN_NAMES)

        # try to read the file
        filename = cls._get_filename(date, ledger_dir, ledger_uid)
        if os.path.exists(filename):
            try:
                df = pd.read_csv(filename, parse_dates=True)
            except pd.errors.EmptyDataError:
                pass

        # convert timestamp to a datetime
        df['timestamp'] = pd.to_datetime(df['timestamp'])

        # success!
        return df
