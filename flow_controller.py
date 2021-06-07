import os
import argparse
import ast
import croniter
import datetime
import logging
import subprocess
import sys
import time
import traceback
import atexit
import socket
import threading
import xmlrpc
from smq import SMQServer, SMQClient, SimpleXMLRPCServerEx
import pandas as pd

LOCK_FILENAME = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'flow_controller.lock')

SMQ_ClientName = 'FlowController_'
SMQ_PUBLIST = ['FlowController.Started', 'FlowController.CQ_Response', 'FlowController.Changed']
SMQ_SUBLIST = ['FlowController.CQ']
CFG_NAME = ''
SMQC = None

# read in the configuration files
def _init_logging():
    # setup logging
    root = logging.getLogger()
    root.setLevel(logging.INFO)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(threadName)s %(message)s'))
    root.addHandler(console_handler)

    file_handler = logging.FileHandler(filename='flow_controller.log')
    file_handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(threadName)s %(message)s'))
    root.addHandler(file_handler)



def ledger_filename(ledger_dir, cfg_uid, date=None):
    if date is None:
        date = datetime.datetime.now().strftime('%Y%m%d')
    
    return os.path.join(ledger_dir, cfg_uid + "." + date + ".ledger")

def update_job_ledger(ledger_dir, cfg_uid, job_name, new_state, reason):
    filename = ledger_filename(ledger_dir, cfg_uid)
    if not os.path.exists(filename):
        f = open(filename, 'w')
        f.write('TIMESTAMP,JOB_NAME,STATE,REASON\n')
        f.close()
        
    f = open(filename, 'r')
    s = f.read()
    f.close()
    f = open(filename, 'w')
    s += datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S") + "," + job_name + "," + new_state + "," + REASON + "\n"
    f.write(s)
    f.close()

def read_job_ledger(ledger_dir, cfg_uid, date=None):
    filename = ledger_filename(ledger_dir, cfg_uid, date)
    if not os.path.exists(filename):
        return pd.DataFrame()
    df = pd.read_csv(filename, parse_dates=True)
    df['TIMESTAMP']= pd.to_datetime(df['TIMESTAMP'])
    return df



class FlowControllerJobs(object):
    def __init__(self):
        """ init """
        self._cfg_filename = None
        self._cfg = None

    def load_from_cfg_file(self, cfg_filename):
        self._cfg_filename = cfg_filename
        self._cfg = self._read_cfg_file()        

    def load_from_existing_cfg(self, cfg):
        self._cfg_filename = None
        self._cfg = cfg        

    def _read_cfg_file(self):
        # execute the config to get the output
        proc = subprocess.Popen(['python3', self._cfg_filename], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        stdout, stderr = proc.communicate()
        if proc.returncode != 0:
            logging.error('Error interpeting config file!')
            logging.error(stdout.decode())
            logging.error(stderr.decode())
            sys.exit(1)    # EPERM
        return ast.literal_eval(stdout.decode())

    def get_uid(self):
        return self._cfg['uid']

    def get_root_jobs(self):
        retval = []
        for j in self._cfg['jobs']:
            if not j['depends']:
                retval.append(j)
        return retval

    def get_jobs(self):
        return self._cfg['jobs']
    
    def get_job_state(self, job_name):
        for j in self._cfg['jobs']:
            if j['name'] == job_name:
                return j.get('job_state', '?')

    def set_job_state(self, ledger_dir, job_name, new_state, reason):
        for j in self._cfg['jobs']:
            if j['name'] == job_name:
                j['job_state'] = new_state
                update_job_ledger(ledger_dir, self._cfg['uid'], job_name, new_state)
    
    def reload_job_states_from_ledger(self, ledger_dir):        
        df = read_job_ledger(ledger_dir, self._cfg['uid'])
        for _, r in df.iterrows():
            for j in self._cfg['jobs']:
                if j['name'] == r['JOB_NAME']:
                    j['job_state'] = r['STATE']


class FlowController():
    def __init__(self):
        self._uid = None
        self._jobs = None
        self._rpc_address = None
        self._rpcserver = None
        self._shutdown = False
        self._smqc = None

    @classmethod
    def discover_all_flow_controllers(cls, smq_server_addr, discovery_time=0.5):
        """ discover all flow controllers
        
            Args:
                discovery_time - time in seconds to wait for pong responses
            
            Returns:
                list of all flow controllers on the smq bus
        """
        # start up a new smq client
        smqc = SMQClient()
        smqc.start_client(smq_server_addr, 'FlowController_Discovery', 'FlowController.CQ', 'FlowController.CQ_Response')
        
        # send a ping message
        smqc.publish_message('FlowController.CQ', '')
        
        # wait for discovery time
        time.sleep(discovery_time)
        
        # read all CQ_Response mesages messages
        retval = []     # client_uid, rpc_addr, cfg_uid
        while True:
            msg = smqc.get_message()
            if msg is None:
                break
            if msg['msg'] == 'FlowController.CQ_Response':
                d = msg['msg_data']
                retval.append({'smq_uid': d['smq_uid'], 'rpc_addr': d['rpc_addr'], 'cfg_uid': d['cfg_uid']})
        
        # success!
        return retval

    @classmethod
    def get_cfg_rpc(cls, rpc_addr):
        with xmlrpc.client.ServerProxy('http://' + rpc_addr[0] + ':' + str(rpc_addr[1]), allow_none=True) as sp:
            return sp.get_cfg()

    @classmethod
    def trigger_job_rpc(cls, rpc_addr, job_name):
        with xmlrpc.client.ServerProxy('http://' + rpc_addr[0] + ':' + str(rpc_addr[1]), allow_none=True) as sp:
            return sp.trigger_job(job_name)

    @classmethod
    def set_job_state_rpc(cls, rpc_addr, job_name, new_state):
        with xmlrpc.client.ServerProxy('http://' + rpc_addr[0] + ':' + str(rpc_addr[1]), allow_none=True) as sp:
            return sp.set_job_state(job_name, new_state)
        
    def get_cfg(self):
        return self._jobs

    def trigger_job(self, job_name):
        # ------------------------------
        # TODO!!!!!! THIS SHOULD RUN THE JOB!
        # ------------------------------
        self.set_job_state(job_name, 'SUCCESS')

    def set_job_state(self, job_name, new_state, reason):
        f = open(LOCK_FILENAME, 'r')
        pid = f.read()
        f.close()
        if pid != str(os.getpid()):
            logging.error('Error!  PID does not match.  Exiting!')
            self._rpcserver.shutdown()
            sys.exit(1)
        
        
        self._jobs.set_job_state(self._ledger_dir, job_name, new_state, reason)
        self._smqc.publish_message('FlowController.Changed', self._jobs.get_uid())

    def _message_handler(self, **kwargs):
        try:
            if kwargs['msg'] == 'FlowController.CQ':
                msg_data = {
                    'smq_uid': self._smqc._client_info['smq_uid'],
                    'rpc_addr': self._rpc_address,
                    'cfg_uid': self._jobs.get_uid()
                    }
                self._smqc.send_direct_message(kwargs['smq_uid'], 'FlowController.CQ_Response', msg_data)            
        except Exception as e:
            logging.error(traceback.format_exc())
            raise(e)

    def start(self, smq_server, cfg_filename, ledger_dir, joblog_dir):
        self._shutdown = False
        self._ledger_dir = ledger_dir
        self._joblog_dir = joblog_dir
        self._jobs = FlowControllerJobs()
        self._jobs.load_from_cfg_file(cfg_filename)
        self._uid = SMQ_ClientName + self._jobs.get_uid()

        self._smqc = SMQClient()
        self._smqc.set_message_handler(self._message_handler)    
        self._smqc.start_client(smq_server, self._uid, ' '.join(SMQ_PUBLIST), ' '.join(SMQ_SUBLIST))
        atexit.register(lambda: self._smqc.shutdown())

        # init the rpc server
        self._rpcserver = SimpleXMLRPCServerEx(('', 0), allow_none=True, logRequests=False)
        self._rpcserver.register_function(self.get_cfg, 'get_cfg')
        self._rpcserver.register_function(self.trigger_job, 'trigger_job')
        self._rpcserver.register_function(self.set_job_state, 'set_job_state')
        
        self._rpc_address = (socket.gethostname(), self._rpcserver.server_address[1])

        # reload states from ledger
        self._jobs.reload_job_states_from_ledger(ledger_dir)
        

        # publish the message
        self._smqc.publish_message('FlowController.Started', '')

        # start the rpc server
        self._rpcserver.serve_forever()

    def shutdown(self):
        self._shutdown = True


def remove_lockfile():
    f = open(LOCK_FILENAME, 'r')
    pid = f.read()
    f.close()
    if pid == str(os.getpid()):
        os.remove(LOCK_FILENAME)

# --------------------------------------------------
#    Main
# --------------------------------------------------



# #print(ledger_filename('.', 'xxx', '20210605'))
# update_job_ledger('.', 'xxx', 'xyz', 'SUCCESS')
# print(read_job_ledger('.', 'xxx'))
# exit(0)




def run(args):
    # check for pid lock file
    if os.path.exists(LOCK_FILENAME):
        raise Exception(f'Error!  The lockfile {LOCK_FILENAME} exists so another instance may be already running.  If you are sure there is no other instance running, please delete the lockfile to continue.')

    f = open(LOCK_FILENAME, 'w')
    f.write(str(os.getpid()))
    f.close()
    
    atexit.register(remove_lockfile)
        
    
    
    
    fc = FlowController()
    fc.start(args['smq_server'], args['config'], args['ledger_dir'], args['joblog_dir'])

if __name__ == "__main__":
    # init the loggers
    _init_logging()
    logging.info('Flow Controller Started')

    try:
        # parse the arguments
        parser = argparse.ArgumentParser(description='Flow Controller')
        parser.add_argument('--config', help='filename of config file to use, i.e. cfg_test.py')
        parser.add_argument('--smq_server', required=True)
        parser.add_argument('--ledger_dir', required=True)
        parser.add_argument('--joblog_dir', required=True)
        args = parser.parse_args()

        # run
        run(vars(args))
    except:
        logging.error(traceback.format_exc())
    finally:
        logging.info('Flow Controller Exiting')



















# def _dag_find_roots(jobs):
#     retval = []
#     for x in jobs:
#         if len(x.get('depends', [])) == 0:
#             retval.append(x)
#     return retval
# 
# 
# def _build_cron_events(jobs):
#     # find cron events
#     cron_events = []
#     for j in jobs:
#         if 'cron' in j:
#             print(j['cron'])
#             j['cron_next_scheduled_time'] = croniter.croniter(j['cron'], datetime.datetime.now()).get_next(datetime)
#             cron_events.append(j)
# 
#     # sort the cron_events by 'cron_next_scheduled_time'
#     cron_events = sorted(cron_events, key=lambda k: k['cron_next_scheduled_time'])
# 
#     # return cron_events
#     return cron_events




#     SMQC[jsc].start_client(smq_server, client_name, pub_list, sub_list)

    
#     print(args)
#     print(args['config'])
# 
# 
#     # sanity check.  jobs can only be cron or dependent, not both
# 
#     cron_events = _build_cron_events(jobs)
# 
# 
#     logging.info('Starting Main Loop')
#     while True:
#         time.sleep(1)
# 
# 
#         # get the current list of completed jobs
#         
#         # check if any existing jobs can now run because of dependent completed jobs
#         for j in jobs:
#             if dependencies_satisfied(j):   # also handles cron jobs, always false if job is running                
#                 run_job(j)                  # will mark the job as currently running.  When the job is finished, the state will be changed out of running
#         



