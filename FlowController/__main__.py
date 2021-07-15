# #!/usr/bin/env python3
# 
# import logging
# import os
# import traceback
# import argparse
# from FlowController import FlowController
# 
# 
# def run(args):
#     fc = FlowController()
#     fc.start(smq_server_url=args['smq_server'], cfg_filename=args['config'], ledger_dir=args['ledger_dir'],
#              joblog_dir=args['joblog_dir'])
#     fc.main_loop()
# 
# 
# if __name__ == "__main__":
#     # init the loggers
#     # setup logging
#     logging.getLogger().setLevel(logging.INFO)
# 
#     console_handler = logging.StreamHandler()
#     console_handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(threadName)s %(message)s'))
#     logging.getLogger().addHandler(console_handler)
#     logging.info('Flow Controller Started')
# 
#     try:
#         # parse the arguments
#         parser = argparse.ArgumentParser(description='Flow Controller')
#         parser.add_argument('--config', help='filename of config file to use, i.e. cfg_test.py')
#         parser.add_argument('--smq_server', required=True)
#         parser.add_argument('--ledger_dir', required=True)
#         parser.add_argument('--joblog_dir', required=True)
#         parser.add_argument('--log_level', default=logging.INFO)
#         args = parser.parse_args()
# 
#         # switch logging level
#         root = logging.getLogger()
#         root.setLevel(args.log_level)
# 
#         # run
#         run(vars(args))
#     except Exception as e:
#         logging.error(traceback.format_exc())
#         raise(e)
#     finally:
#         logging.info('Flow Controller Exiting')
