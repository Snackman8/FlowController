# cron job

def get_jobs():
    return [
        # example of a cron type job
        {'name': 'test_cron_job_5',
         'cron': '*/5 * * * *',     # run every 5 minutes
         'run_python_script': 'xxx.py'},    # run a python script.
                                            # Return EAGAIN for try again which will set node to RETRYING state
                                            # Return EOK for success, success message on SMQ will be broadcast

        # example of a job that depends on another job
        {'name': 'test_dep_cron_job',
         'periodicity': 'daily',
         'depends': ['test_cron_job'],
         'run_shell_cmd': """echo "hello world!" """
         },

        {'name': 'test_dep_cron_job2',
         'periodicity': 'daily',
         'depends': ['test_dep_cron_job'],
         'run_shell_cmd': """echo "hello world!" """
         },

        # example of a job that depends on several other jobs
        {'name': 'test_multiple_deps',
         'periodicity': 'daily',
         'depends': ['test_dep_cron_job', 'test_dep_cron_job2'],
         'run_shell_cmd': """echo "hello world!" """
         },

    ]

print(get_jobs())