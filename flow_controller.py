
import argparse
import ast
import croniter
import datetime
import logging
import subprocess
import sys
import time
import traceback


#from smq import SMQClient

# if we restart the flow controller on a different server, what will happen?
# we can broadcast a shutdown message so all other servers shutdown
# then we can reload the config file and restart the flowcontroller on this server

# how do we bind the cfg_uid to an rpc?



SMQ_ClientName = 'FlowController'
SMQ_PUBLIST = ['FlowController.kill', 'FlowController.ping_cfg']
SMQ_SUBLIST = SMQ_PUBLIST


# read in the configuration files
def _init_logging():
    # setup logging
    root = logging.getLogger()
    root.setLevel(logging.INFO)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s - %(message)s', datefmt='%Y%m%d %H:%M:%S'))
    root.addHandler(console_handler)

    file_handler = logging.FileHandler(filename='flow_controller.log')
    file_handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s - %(message)s', datefmt='%Y%m%d %H:%M:%S'))
    root.addHandler(file_handler)



def _dag_find_roots(jobs):
    retval = []
    for x in jobs:
        if len(x.get('depends', [])) == 0:
            retval.append(x)
    return retval


def _build_cron_events(jobs):
    # find cron events
    cron_events = []
    for j in jobs:
        if 'cron' in j:
            print(j['cron'])
            j['cron_next_scheduled_time'] = croniter.croniter(j['cron'], datetime.datetime.now()).get_next(datetime)
            cron_events.append(j)

    # sort the cron_events by 'cron_next_scheduled_time'
    cron_events = sorted(cron_events, key=lambda k: k['cron_next_scheduled_time'])

    # return cron_events
    return cron_events


class FlowControllerJobs(object):
    def __init__(self, cfg_filename):
        """ init """
        self._cfg_filename = cfg_filename
        self._cfg = self._read_cfg_file()

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

    def get_root_jobs(self):
        retval = []
        for j in self._cfg['jobs']:
            if not j['depends']:
                retval.append(j)
        return retval

    def get_jobs(self):
        return self._cfg['jobs']


class FlowController(object):
    def __init__(self):
        self._shutdown = False

    def start(self, cfg_filename):
        self._shutdown = False
        self._cfg_filename = cfg_filename
        while not self._shutdown:
            pass

    def shutdown(self):
        self._shutdown = True


def run(args):
    pass
#    smqc = SMQClient()
#    smqc.start_client(args['smq_server'], SMQ_ClientName, SMQ_PUBLIST, SMQ_SUBLIST)
    

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




if __name__ == "__main__":
    # init the loggers
    _init_logging()
    logging.info('Flow Controller Started')

    try:
        # parse the arguments
        parser = argparse.ArgumentParser(description='Flow Controller')
        parser.add_argument('--config', help='filename of config file to use, i.e. cfg_test.py')
        parser.add_argument('--smq_server')
        args = parser.parse_args()

        # run
        run(vars(args))
    except:
        logging.error(traceback.format_exc())
    finally:
        logging.info('Flow Controller Exiting')
