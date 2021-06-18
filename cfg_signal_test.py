CFG_UID = 'signal_test'
CFG_TITLE = 'Test Config For Flow Controller'

def get_jobs():
    return [
        # premarket parent node for gui
        {'name': 'premarket_data',
         'x_offset': 0,
         'y_offset': 0,
         'width': 200},

        # premarket for TQQQ
        {'name': 'get_data_premarket_TQQQ',
         'cron': '15 6 * * 1-5',     # runs at 6:15am
         'run_cmd': './echo_sleep_job.py --echo_text "AAAAA" --sleep_time 5',
         'depends': ['premarket_data']},

        # premarket for UDOW
        {'name': 'get_data_premarket_UDOW',
         'cron': '15 6 * * 3',     # runs at 6:15am
         'run_python_script': 'data/get_data_alpha_vantage.py UDOW',
         'depends': ['premarket_data']},

        # premarket for SPXL
        {'name': 'get_data_premarket_SPXL',
         'cron': '15 6 * * *',     # runs at 6:15am
         'run_python_script': 'data/get_data_alpha_vantage.py SPXL',
         'depends': ['premarket_data']},

        # premarket for TNA
        {'name': 'get_data_premarket_TNA',
         'cron': '15 6 * * *',     # runs at 6:15am
         'run_python_script': 'data/get_data_alpha_vantage.py TNA',
         'depends': ['premarket_data']},

        # cron jobs
        # aftermarket parent node for gui
        {'name': 'cron_jobs',
         'x_offset': 0,
         'y_offset': 150,
         'width': 200},

        # inflow paycheck signal
        {'name': 'inflow_paycheck_signal',
         'cron': '0 5 * * *',     # runs at 5am
         'run_python_script': 'signals/inflow_paycheck_signal.py',
         'depends': ['cron_jobs']},

        # earnings_soon_signal
        {'name': 'earnings_soon_signal',
         'cron': '0 5 * * *',     # runs at 5am
         'run_python_script': 'signals/earnings_soon_signal.py',
         'depends': ['cron_jobs']},

        # aftermarket parent node for gui
        {'name': 'afterhours_data',
         'x_offset': 0,
         'y_offset': 300,
         'width': 200},

        # afterhours for TQQQ
        {'name': 'get_data_afterhours_TQQQ',
         'cron': '15 13 * * *',     # runs at 1:15am
         'run_python_script': 'data/get_data_alpha_vantage.py TQQQ',
         'depends': ['afterhours_data']},

        # afterhours for UDOW
        {'name': 'get_data_afterhours_UDOW',
         'job_type': 'cron',
         'cron': '15 13 * * *',     # runs at 1:15am
         'run_python_script': 'data/get_data_alpha_vantage.py UDOW',
         'depends': ['afterhours_data']},

        # afterhours for SPXL
        {'name': 'get_data_afterhours_SPXL',
         'cron': '15 13 * * *',     # runs at 1:15am
         'run_python_script': 'data/get_data_alpha_vantage.py SPXL',
         'depends': ['afterhours_data']},

        # afterhours for TNA
        {'name': 'get_data_afterhours_TNA',
         'cron': '15 13 * * *',     # runs at 1:15am
         'run_python_script': 'data/get_data_alpha_vantage.py TNA',
         'depends': ['afterhours_data']},

        # momentum signal
        {'name': 'morning_momentum_signal',
         'run_python_script': 'signals/momentum_signal.py',
         'depends': ['inflow_paycheck_signal', 'get_data_premarket_TQQQ', 'get_data_premarket_UDOW', 'get_data_premarket_SPXL', 'get_data_premarket_TNA', 'earnings_soon_signal'],
         'x_offset': 0,
         'y_offset': -100},

        # buy sell
        {'name': 'morning_buy_sell',
         'run_python_script': 'staging/generate_buy_sell.py',
         'depends': ['morning_momentum_signal']},

        # execute etf
        {'name': 'morning_execute_etf_trades',
         'run_python_script': 'staging/execute_etf_trades.py',
         'depends': ['morning_buy_sell']},

        # execute options
        {'name': 'morning_execute_option_trades',
         'run_python_script': 'staging/execute_option_trades.py',
         'depends': ['morning_buy_sell']},

        # execute futures
        {'name': 'morning_execute_future_trades',
         'run_python_script': 'staging/execute_future_trades.py',
         'depends': ['morning_buy_sell']},

        # execute equities
        {'name': 'morning_execute_equity_trades',
         'run_python_script': 'staging/execute_equity_trades.py',
         'depends': ['morning_buy_sell']},

        # momentum signal
        {'name': 'afternoon_momentum_signal',
         'run_python_script': 'signals/momentum_signal.py',
         'depends': ['inflow_paycheck_signal', 'get_data_afterhours_TQQQ', 'get_data_afterhours_UDOW', 'get_data_afterhours_SPXL', 'get_data_afterhours_TNA', 'earnings_soon_signal'],
         'x_offset': 0,
         'y_offset': 150},

        # buy sell
        {'name': 'afternoon_buy_sell',
         'run_python_script': 'staging/generate_buy_sell.py',
         'depends': ['afternoon_momentum_signal']},

        # execute etf
        {'name': 'afternoon_execute_etf_trades',
         'run_python_script': 'staging/execute_etf_trades.py',
         'depends': ['afternoon_buy_sell']},

        # execute options
        {'name': 'afternoon_execute_option_trades',
         'run_python_script': 'staging/execute_option_trades.py',
         'depends': ['afternoon_buy_sell']},

        # execute futures
        {'name': 'afternoon_execute_future_trades',
         'run_python_script': 'staging/execute_future_trades.py',
         'depends': ['afternoon_buy_sell']},

        # execute equities
        {'name': 'afternoon_execute_equity_trades',
         'run_python_script': 'staging/execute_equity_trades.py',
         'depends': ['afternoon_buy_sell']},
    ]


# --------------------------------------------------
#    Main
# --------------------------------------------------
if __name__ == '__main__':
    # print the info to stdout
    cfg = {
        'title': CFG_TITLE,
        'uid': CFG_UID,        
        'jobs': get_jobs()}
    print(cfg)
