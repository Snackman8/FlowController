import io
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
from functools import partial
import atexit
import socket
import threading
import xmlrpc
from smq import SMQServer, SMQClient, SimpleXMLRPCServerEx
import pandas as pd
import subprocess

SMQ_ClientName = 'FlowController_'
SMQ_PUBLIST = ['FlowController.Started', 'FlowController.CQ_Response', 'FlowController.Changed']
SMQ_SUBLIST = ['FlowController.CQ']


STATE_READY = 'READY'
STATE_PENDING = 'PENDING'
STATE_RUNNING = 'RUNNING'
STATE_SUCCESS = 'SUCCESS'
STATE_FAIL = 'FAIL'

class FlowControllerLedger():
    def __init__(self, ledger_dir, uid):
        self._column_names = ['timestamp', 'job_name', 'state', 'reason']
        self._ledger_dir = ledger_dir
        self._uid = uid
        
    def _get_filename(self, date):
        # sanity check
        datetime.datetime.strptime(date, '%Y%m%d')
        return os.path.join(self._ledger_dir, self._uid + "." + date + ".ledger")

    def append(self, job_name, state, reason):
        # create a new file if it does not exist
        d = datetime.datetime.now()
        filename = self._get_filename(d.strftime('%Y%m%d'))
        if not os.path.exists(filename):
            with open(filename, 'w') as f:
                f.write(','.join(self._column_names) + '\n')
        
        # append to the file
        with open(filename, 'a') as f:
            timestamp = d.strftime("%Y-%m-%d %H:%M:%S")
            f.write(f"{timestamp},{job_name},{state},{reason}\n")
        
    def read(self, date=None):
        # default dataframe if file does not exist or is empty
        if date is None:
            date = datetime.datetime.now().strftime('%Y%m%d')
            
        df = pd.DataFrame(columns=self._column_names)
        
        # try to read the file
        filename = self._get_filename(date)
        if os.path.exists(filename):
            try:
                df = pd.read_csv(filename, parse_dates=True)
                create_fake_file = False
            except pd.errors.EmptyDataError:
                pass
        
        # convert timestamp to a datetime
        df['timestamp']= pd.to_datetime(df['timestamp'])
        
        # success!
        return df


class FlowControllerJobReader():
    def __init__(self, existing_cfg):
        """
            cfg['filename']
            cfg['uid']
            cfg['jobs']
            cfg['joblog_dir']
        """
        self._cfg = existing_cfg
                
        # build a job dict and extract root jobs
        self._job_dict = {}
        self._cron_job_names = []
        self._root_job_names = []
        self._joblog_dir = self._cfg['joblog_dir']
        for j in self._cfg['jobs']:
            # build the job dictionary
            self._job_dict[j['name']] = j
            
            # find root nodes
            if not j.get('depends', []) and 'cron' not in j:
                self._root_job_names.append(j['name'])

            # find cron nodes
            if 'cron' in j:
                self._cron_job_names.append(j['name'])

            # set the initial state
            j['state'] = j.get('state', STATE_READY)

    def get_log_filename(self, job_name, date=None):
        if date is None:
            date = datetime.datetime.now()
        return os.path.abspath(os.path.join(self._joblog_dir, f"{job_name}.{datetime.datetime.now().strftime('%Y%m%d')}.log"))

    def get_job_state(self, job_name):
        return self._job_dict[job_name]['state']

    def get_job_dict(self):
        return self._job_dict

    def get_uid(self):
        return self._cfg['uid']
    
    def query_cron_job_names(self):
        return self._cron_job_names

    def query_root_job_names(self):
        return self._root_job_names

    def query_job_names_by_state(self, state):
        retval = []
        for k, v in self._job_dict.items():
            if v['state'] == state:
                retval.append(k)
        return retval
                

class FlowControllerJobManager(FlowControllerJobReader):
    def __init__(self, ledger_dir, cfg_filename, joblog_dir):
        # init
        self._cfg_filename = cfg_filename
        self._ledger_dir = ledger_dir
        self._set_state_queue = []
        self._joblog_dir = joblog_dir
        self._reload_needed = False

        # reload
        self.reload()
                
    def _read_cfg_file(self, cfg_filename):
        # execute the config to get the output
        proc = subprocess.Popen(['python3', cfg_filename], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        stdout, stderr = proc.communicate()
        if proc.returncode != 0:
            logging.error('Error interpeting config file!')
            logging.error(stdout.decode())
            logging.error(stderr.decode())
            sys.exit(1)    # EPERM
        cfg = ast.literal_eval(stdout.decode())
        cfg['filename'] = cfg_filename
        cfg['joblog_dir'] = self._joblog_dir
        print(cfg['title'])
        return cfg

    def handle_job_state_updates(self):
        """ 
            Call to process to the queue of job state changes

            ** this function is not thread safe """
        changes = False
        while self._set_state_queue:
            job_name, new_state, reason = self._set_state_queue.pop(0)
            self._ledger.append(job_name, new_state, reason)
            self._job_dict[job_name]['state'] = new_state
            changes = True
        return changes

    def reload(self):
        # init the base FlowcontrollerJobReader
        cfg = self._read_cfg_file(self._cfg_filename)
        super().__init__(cfg)
        
        # init the ledger
        self._ledger = FlowControllerLedger(self._ledger_dir, self.get_uid())
        
        # update the states from the ledger
        df = self._ledger.read()
        for _, r in df.iterrows():
            for j in self._job_dict.values():
                if j['name'] == r['job_name']:
                    j['state'] = r['state']
        
        # setup the next cron job fire time
        base = datetime.datetime.now()
        for cjn in self.query_cron_job_names():
            self.update_next_cron_fire_time(cjn, base)            

    def request_reload_cfg(self):
        self._reload_needed = True

    def set_job_state(self, job_name, new_state, reason):
        # append to the state manager
        self._set_state_queue.append((job_name, new_state, reason))
    
    def set_jobs_with_dependencies_met_to_pending(self):
        for j in self._job_dict.values():
            # skip job it it does not depend on anything
            if 'depends' not in j:
                continue

            # skip job if it is not ready
            if self.get_job_state(j['name']) != STATE_READY:
                continue
        
            # loop through the depends of the job and check for success
            trigger_job = True
            for jdn in j['depends']:
                if self.get_job_state(jdn) != STATE_SUCCESS:
                    trigger_job = False
                    break
            if trigger_job:
                self.set_job_state(j['name'], STATE_PENDING, 'Dependencies Ready')            

    def update_next_cron_fire_time(self, job_name, base):
        iter = croniter.croniter(self._job_dict[job_name]['cron'], base)
        self._job_dict[job_name]['next_cron_fire_time'] = iter.get_next(datetime.datetime)


class FlowControllerRPCClient():
    def __init__(self, rpc_url):
        self._rpc_url = rpc_url

    def get_jobs_snapshot(self):
        with xmlrpc.client.ServerProxy(self._rpc_url, allow_none=True) as sp:
            current_cfg = sp.get_current_cfg()
            return FlowControllerJobReader(current_cfg)

    def reload_cfg(self):
        with xmlrpc.client.ServerProxy(self._rpc_url, allow_none=True) as sp:
            sp.reload_cfg()

    def set_job_state(self, job_name, new_state, reason):
        with xmlrpc.client.ServerProxy(self._rpc_url, allow_none=True) as sp:
            sp.set_job_state(job_name, new_state, reason)

    def trigger_job(self, job_name, reason):
        self.set_job_state(job_name, STATE_PENDING, reason)

    def _message_handler(self, **kwargs):
        pass

    def start(self, **kwargs):
        pass

    def shutdown(self, **kwargs):
        pass


class FlowControllerMixInBase():
    def __init__(self, **kwargs):
        pass
    
    def start(self, **kwargs):
        pass
    
    def shutdown(self, **kwargs):
        pass
    
    def _message_handler(self, **kwargs):
        pass

class FlowControllerRPCMixIn(FlowControllerMixInBase):
    def __init__(self):
        self._rpc_server = None
        self._rpc_server_thread = None
        self._rpc_url = None

    def start(self, **kwargs):
        # init the rpc server
        self._rpc_server = SimpleXMLRPCServerEx(('', 0), allow_none=True, logRequests=False)
        self._rpc_server.register_function(lambda: self._job_manager._cfg, 'get_current_cfg')
        self._rpc_server.register_function(lambda: self._job_manager.request_reload_cfg(), 'reload_cfg')
        self._rpc_server.register_function(
            lambda job_name, new_state, reason: self._job_manager.set_job_state(job_name, new_state, reason),
            'set_job_state')
        self._rpc_url = 'http://' + socket.gethostname() + ':' + str(self._rpc_server.server_address[1])
        print(self._rpc_url)

        # start        
        self._rpc_server_thread = threading.Thread(target=lambda: self._rpc_server.serve_forever(), daemon=True)
        self._rpc_server_thread.start()
    
    def shutdown(self):
        self._rpc_server.shutdown()


class FlowControllerDiscoveryMixIn(FlowControllerMixInBase):
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

    def _message_handler(self, **kwargs):
        print('MIXIN')
        try:
            if kwargs['msg'] == 'FlowController.CQ':
                msg_data = {
                    'smq_uid': self._smqc._client_info['smq_uid'],
                    'rpc_addr': self._rpc_url,
                    'cfg_uid': self._job_manager.get_uid()
                    }
                self._smqc.send_direct_message(kwargs['smq_uid'], 'FlowController.CQ_Response', msg_data)            
        except Exception as e:
            logging.error(traceback.format_exc())
            raise(e)

    
class FlowControllerBase(FlowControllerMixInBase):
    def __init__(self):
#        self._joblog_dir = None
        self._job_manager = None
        self._job_pids = set()
        self._shutdown = False
        self._smq_uid = None
        self._smqc = None

    def pid_lock(self):
        try:
            # check for pid lock file
            lock_filename = os.path.splitext(os.path.basename(__file__))[0] + '.lock'
            if os.path.exists(lock_filename):
                raise Exception(f'Error!  The lockfile {lock_filename} exists so another instance may be already running.  ' +
                                'If you are sure there is no other instance running, please delete the lockfile to continue.')
            
            # lock
            with open(lock_filename, 'w') as f:
                f.write(str(os.getpid()))
        
            # at exit, remove the lockfile
            def remove_lockfile(lock_filename):
                f = open(lock_filename, 'r')
                pid = f.read()
                f.close()
                if pid == str(os.getpid()):
                    os.remove(lock_filename)
            atexit.register(partial(remove_lockfile, lock_filename))
        except:
            logging.error(traceback.format_exc())
            exit(1) # EPERM error code

    def pid_verify(self):
        try:
            lock_filename = os.path.splitext(os.path.basename(__file__))[0] + '.lock'
            with open(lock_filename, 'r') as f:
                s = f.read()
                if str(os.getpid()) != s:
                    raise Exception(f'Error!  The lockfile {lock_filename} pid of {s} does not match pid of {os.getpid()}')
        except:
            logging.error(traceback.format_exc())
            exit(1)

    def run_job_in_separate_process(self, job_name):
        # TODO: Change to process and track PIDs in self._job_pids
        def threadworker_run_job(job_name):
            job = self._job_manager.get_job_dict()[job_name]
            proc = subprocess.Popen(job['run_cmd'], cwd=os.getcwd(), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, shell=True)

            # setup the logger
#            log_filename = os.path.abspath(os.path.join(self._joblog_dir, f"{job_name}.{datetime.datetime.now().strftime('%Y%m%d')}.log"))
            log_filename = self._job_manager.get_log_filename(job_name)
            print(log_filename)            
            logger = logging.getLogger(f"{job_name}.{datetime.datetime.now().strftime('%Y%m%d')}")
            logger.setLevel(logging.INFO)
            if not logger.handlers:
                file_handler = logging.FileHandler(filename=log_filename)
                file_handler.setFormatter(logging.Formatter('%(asctime)s %(message)s'))
                logger.addHandler(file_handler)
            
            logger.info('')
            logger.info('')
            logger.info('FlowController Starting Job')
            logger.info('')
            logger.info('')
            while True:
                output = proc.stdout.readline()
                if len(output) == 0 and proc.poll() is not None:
                    break
                if output:
                    logger.info(output.strip().decode())
                    logger.handlers[0].flush()
            rc = proc.poll()
            if rc == 0:
                self._job_manager.set_job_state(job_name, STATE_SUCCESS, 'job completed')
            else:
                self._job_manager.set_job_state(job_name, STATE_FAIL, 'job completed')                
            return rc

        t = threading.Thread(target=threadworker_run_job, args=(job_name,))
        t.start()

    def start(self, smq_server_url, cfg_filename, ledger_dir, joblog_dir, **kwargs):
        # init
        self._shutdown = False
#        self._joblog_dir = joblog_dir
        
        # lock to pid
        self.pid_lock()

        # setup the job manager
        self._job_manager = FlowControllerJobManager(ledger_dir, cfg_filename, joblog_dir)
        
        # start the smq client
        self._smq_uid = SMQ_ClientName + self._job_manager.get_uid()        
        self._smqc = SMQClient()
        self._smqc.start_client(smq_server_url, self._smq_uid, ' '.join(SMQ_PUBLIST), ' '.join(SMQ_SUBLIST), message_handler=self._message_handler)

        # trigger any jobs with dependencies met
        self._job_manager.set_jobs_with_dependencies_met_to_pending()        

    def shutdown(self):
        self._shutdown = True

    def main_loop(self):
        last_cron_check = datetime.datetime.now() - datetime.timedelta(seconds=60)
        current_date = datetime.datetime.now().strftime('%Y%m%d')
        while not self._shutdown:
            # pid_verify
            self.pid_verify()
            
            # check if we need to reload
            if self._job_manager._reload_needed:
                self._job_manager._reload_needed = False
                self._job_manager.reload()
                self._smqc.publish_message('FlowController.Changed', self._job_manager.get_uid())

            # check for a new day
            if current_date != datetime.datetime.now().strftime('%Y%m%d'):
                current_date = datetime.datetime.now().strftime('%Y%m%d')
                self._job_manager.reload()                 
                self._smqc.publish_message('FlowController.Changed', self._job_manager.get_uid())

            # handle job manager processing
            if self._job_manager.handle_job_state_updates():
                self._smqc.publish_message('FlowController.Changed', self._job_manager.get_uid())
            
            # handle any cron jobs that are ready to fire
            date = datetime.datetime.now()
            if date > last_cron_check + datetime.timedelta(seconds=60):
                last_cron_check = date
                
                # find all the cron jobs
                for cjn in self._job_manager.query_cron_job_names():
                    if date > self._job_manager._job_dict[cjn]['next_cron_fire_time']:
                        self._job_manager.update_next_cron_fire_time(cjn, date)
                        self._job_manager.set_job_state(cjn, STATE_PENDING, 'cron fire time')
            
            # add pending jobs to the queue            
            for job_name in self._job_manager.query_job_names_by_state(STATE_PENDING):
                self._job_manager.set_job_state(job_name, STATE_RUNNING, 'pending')                
                self.run_job_in_separate_process(job_name)

            # trigger any jobs with dependencies met
            self._job_manager.set_jobs_with_dependencies_met_to_pending()        
             
            # delay
            time.sleep(0.1)

            
class FlowController(FlowControllerBase, FlowControllerDiscoveryMixIn, FlowControllerRPCMixIn):
    def __init__(self, **kwargs):
        # init base classes
        FlowControllerBase.__init__(self, **kwargs)
        FlowControllerDiscoveryMixIn.__init__(self, **kwargs)
        FlowControllerRPCMixIn.__init__(self, **kwargs)

    def _message_handler(self, **kwargs):
        FlowControllerBase._message_handler(self, **kwargs)
        FlowControllerDiscoveryMixIn._message_handler(self, **kwargs)
        FlowControllerRPCMixIn._message_handler(self, **kwargs)

    def start(self, **kwargs):
        FlowControllerBase.start(self, **kwargs)
        FlowControllerDiscoveryMixIn.start(self, **kwargs)
        FlowControllerRPCMixIn.start(self, **kwargs)

    def shutdown(self):
        FlowControllerBase.shutdown()
        FlowControllerDiscoveryMixIn.shutdown()
        FlowControllerRPCMixIn.shutdown()


def _init_logging():
    """ setup logging, will automatically create log file with same name as this file """
    # setup logging
    root = logging.getLogger()
    root.setLevel(logging.INFO)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(threadName)s %(message)s'))
    root.addHandler(console_handler)

    file_handler = logging.FileHandler(filename=os.path.splitext(os.path.basename(__file__))[0] + '.log')
    file_handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(threadName)s %(message)s'))
    root.addHandler(file_handler)


def run(args):
    fc = FlowController()
    fc.start(smq_server_url=args['smq_server'], cfg_filename=args['config'], ledger_dir=args['ledger_dir'], joblog_dir=args['joblog_dir'])
    fc.main_loop()

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
    except Exception as e:
        logging.error(traceback.format_exc())
        raise(e)
    finally:
        logging.info('Flow Controller Exiting')
