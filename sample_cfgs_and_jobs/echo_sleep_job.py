#!/usr/bin/python3

# --------------------------------------------------
#    Import
# --------------------------------------------------
import argparse
import os
import time


# --------------------------------------------------
#    Main
# --------------------------------------------------
def run(args):
    # echo the text
    print("ECHO SLEEP JOB")
    print(f"PID = {os.getpid()}")
    print(f"ECHO TEXT = {args['echo_text']}")

    # sleep
#    time.sleep(int(args['sleep_time']))
    for i in range(0, 20):
        time.sleep(0.1)
        print(i, flush=True)

    print("EXITING")
    exit(0)


if __name__ == "__main__":
    # parse the arguments
    parser = argparse.ArgumentParser(description='Echo Sleep Job')
    parser.add_argument('--echo_text')
    parser.add_argument('--sleep_time')
    args = parser.parse_args()

    # run
    run(vars(args))
