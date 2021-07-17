# --------------------------------------------------
#    Imports
# --------------------------------------------------
import argparse
import logging
import os
import signal
import traceback
from urllib.parse import parse_qs

from pylinkjs.PyLinkJS import run_pylinkjs_app, get_all_jsclients
from FlowController.FlowController import JobState
from SimpleMessageQueue.SMQ_Client import SMQ_Client


# --------------------------------------------------
#    Global Variables
# --------------------------------------------------
SMQC = None

COLOR_MAPPING = {
    JobState.IDLE: '#FFEF02',
    JobState.PENDING: 'lightsalmon',
    JobState.RUNNING: 'mediumaquamarine',
    JobState.SUCCESS: 'seagreen',
    JobState.FAILURE: 'firebrick',
}

LINK_COLOR_MAPPING = {
    JobState.IDLE: '#B0B0B0',
    JobState.PENDING: 'lightsalmon',
    JobState.RUNNING: 'mediumaquamarine',
    JobState.SUCCESS: 'seagreen',
    JobState.FAILURE: 'firebrick',
}


# --------------------------------------------------
#    Private Functions
# --------------------------------------------------
def _pretty_cron(s):
    dayofweek = ('Su', 'Mo', 'Tu', 'W', 'Th', 'F', 'Sa')
    try:
        retval = '['
        f = s.split(' ')
        if f[0] != '*' and f[1] != '*':
            retval += f"{int(f[1]):02}:{int(f[0]):02}" + ' '

        if f[2] != '*' or f[3] != '*':
            raise Exception('Can not handle day and month yet')

        if f[4] != '*':
            ff = f[4].split('-')
            if len(ff) not in (1, 2):
                raise Exception(f'Can not handle day of week format of {f[4]}')
            retval += dayofweek[int(ff[0])]
            if len(ff) == 2:
                retval += '-' + dayofweek[int(ff[1])]
            retval += ' '
    except Exception as _:
        retval = '[? '
    return retval[:-1] + '] '


def _convert_job_to_guinode(j):
    # default values for gui nodes
    defaults = {
        'text_prefix': '',
        'width': 300,
        'depends': [],
        'x': 0,
        'y': 0,
        'x_offset': 0,
        'y_offset': 0,
        'icon_radius': 7,
        'text_color': '#000000',
        'text_padding_left': 4,
        'text_padding_right': 4,
        'icon_shape': 'circle',
        'no_context_menu': False,
        'parent_curve_settings': []}

    # copy the default values
    gn = dict(j)
    for k, v in defaults.items():
        if k not in gn:
            gn[k] = v

    # if no depends, then we don't show an icon
    if not gn['depends']:
        gn['icon_shape'] = 'none'
        gn['no_context_menu'] = True

    # add a pretty cron
    if gn['text_prefix'] == '':
        if 'cron' in gn:
            gn['text_prefix'] = _pretty_cron(gn['cron'])

    # set some derived values
    gn['children'] = []
    gn['children_rendered'] = []
    gn['parents'] = []
    gn['text'] = gn.get('text', gn['name'])

    gn['state'] = JobState[gn['state']]

    job_state = gn['state']
    gn['icon_color'] = COLOR_MAPPING.get(job_state, 'gainsboro')
    gn['link_color'] = LINK_COLOR_MAPPING.get(job_state, 'gainsboro')

    # success!
    return gn


def _convert_cfg_to_gui_nodes(config_snapshot):
    # convert the cfg nodes to gui nodes
    gui_jobs = config_snapshot['jobs']
    gui_jobs = {k: _convert_job_to_guinode(v) for k, v in gui_jobs.items()}

    # repoint the depends to parent gui nodes, and find roots at the same time
    stack = []
    for j in gui_jobs.values():
        if not j['depends']:
            stack.append(j)
        else:
            for pjn in j['depends']:
                j['parents'].append(gui_jobs[pjn])
                gui_jobs[pjn]['children'].append(j)

            # fix any missing curve settings
            for i in range(0, len(j['parents'])):
                if len(j['parent_curve_settings']) <= i:
                    j['parent_curve_settings'].append(None)
                if j['parent_curve_settings'][i] is None:
                    j['parent_curve_settings'][i] = [[0.5, 0], [0.75, 1]]

    # do our best to traverse the nodes in order, i think it might be ok to be circular sometimes
    processed = set()
    for j in gui_jobs.values():
        if j not in stack:
            stack.append(j)
    while stack:
        j = stack.pop(0)
        if j['parents']:
            if j['parents'][0]['name'] in processed:
                # parent already processed so we can computer our x and y
                j['x'] = j['parents'][0]['x_render'] + j['parents'][0]['width']
                j['y'] = j['parents'][0]['y_render'] + (len(j['parents'][0]['children_rendered']) -
                                                        (len(j['parents'][0]['children']) - 1) / 2.0) * 30
                j['parents'][0]['children_rendered'].append(j)
            else:
                # parent hasn't been processed yet, so reinsert into the stack
                stack.remove(j['parents'][0])
                stack.insert(j)
                stack.insert(j['parents'][0], 0)
                continue
        processed.add(j['name'])
        j['x_render'] = j['x'] + j['x_offset']
        j['y_render'] = j['y'] + j['y_offset']
        j['x_rendertext'] = j['x_render'] + j['icon_radius'] * 1.5
        j['y_rendertext'] = j['y_render']

    return gui_jobs


def _generate_draw_job_node_js(jsc, node_info):
    js = ""
    if node_info['icon_shape'] == 'circle':
        js = f"""
            gCtx.beginPath();
            gCtx.strokeStyle = "{node_info['icon_color']}";
            gCtx.strokeStyle = "#B0B0B0";
            gCtx.fillStyle = "{node_info['icon_color']}";
            gCtx.arc({node_info['x_render']}, {node_info['y_render']}, {node_info['icon_radius']}, 0, Math.PI * 2, true);
            gCtx.stroke();
            gCtx.fill();
        """
    js += f"""
        var t = "{node_info['text_prefix']}" + "{node_info['text']}";
        gCtx.fillStyle = "{node_info['text_color']}";
        gCtx.fillText(t, {node_info['x_rendertext'] + node_info['text_padding_left']}, {node_info['y_render']});

        if (({node_info['x_render']} - {node_info['icon_radius']}) < gBoundingBox[0]) {{
            gBoundingBox[0] = ({node_info['x_render']} - {node_info['icon_radius']});
        }}

        if (({node_info['y_render']} - {node_info['icon_radius']}) < gBoundingBox[1]) {{
            gBoundingBox[1] = ({node_info['y_render']} - {node_info['icon_radius']});
        }}

        if (({node_info['x_rendertext']} + gCtx.measureText(t).width + {node_info['text_padding_left']}) > gBoundingBox[2]) {{
            gBoundingBox[2] = ({node_info['x_rendertext']} + gCtx.measureText(t).width + {node_info['text_padding_left']});
        }}

        if (({node_info['y_render']} + {node_info['icon_radius']}) > gBoundingBox[3]) {{
            gBoundingBox[3] = ({node_info['y_render']} + {node_info['icon_radius']});
        }}
    """

    if node_info['parents'] is not None:
        for i, p in enumerate(node_info['parents']):
            js += f"""
                    var t = "{p['text_prefix']}" + "{p['text']}";
                """
            pc = node_info['parent_curve_settings'][i]
            sx = f"""({p['x_rendertext']} + gCtx.measureText(t).width + {node_info['text_padding_left']}) + 4"""
            sy = f"""({p['y_render']})"""
            ex = f"""({node_info['x_render'] - node_info['icon_radius']})"""
            ey = f"""({node_info['y_render']})"""
            cx1 = f"""({sx} + ({ex} - {sx}) * {pc[0][0]})"""
            cy1 = f"""({sy} + ({ey} - {sy}) * {pc[0][1]})"""
            cx2 = f"""({sx} + ({ex} - {sx}) * {pc[1][0]})"""
            cy2 = f"""({sy} + ({ey} - {sy}) * {pc[1][1]})"""
            js += f"""
            gCtx.beginPath();
            gCtx.strokeStyle = "{p['link_color']}";
            gCtx.moveTo({sx}, {sy});
            gCtx.bezierCurveTo({cx1}, {cy1}, {cx2}, {cy2}, {ex}, {ey});
            gCtx.stroke();
            """

    return js


# --------------------------------------------------
#    Javascript Callbacks
# --------------------------------------------------
def admin_menu_click(jsc, item_text):
    if item_text == 'Reload Config':
        SMQC.send_message(SMQC.construct_msg('reload_config', jsc.tag['cfg_uid'], {}),
                          response_callback=on_reload_config_response)

#        jsc.tag['FlowControllerRPC'].reload_cfg()

    if item_text == 'Autofit':
        jsc.eval_js_code(blocking=False, js_code="""$('#btn_autofit').click()""")

    if item_text == 'Refresh':
        reconnect_cfg_view(jsc, *jsc.tag['url_args'])


def context_menu_click(jsc, item_text, job_name):
    if item_text == 'Trigger Job':
        SMQC.send_message(SMQC.construct_msg('trigger_job', jsc.tag['cfg_uid'],
                                             {'job_name': job_name,
                                              'reason': 'manually set by user ?'}))

    if item_text == 'Set as Ready':
        SMQC.send_message(SMQC.construct_msg('change_job_state', jsc.tag['cfg_uid'],
                                             {'job_name': job_name, 'new_state': 'IDLE',
                                              'reason': 'manually set by user ?'}))

    if item_text == 'Set as Success':
        SMQC.send_message(SMQC.construct_msg('change_job_state', jsc.tag['cfg_uid'],
                                             {'job_name': job_name, 'new_state': 'SUCCESS',
                                              'reason': 'manually set by user ?'}))

    if item_text == 'Set as Fail':
        SMQC.send_message(SMQC.construct_msg('change_job_state', jsc.tag['cfg_uid'],
                                             {'job_name': job_name, 'new_state': 'FAILURE',
                                              'reason': 'manually set by user ?'}))


def canvas_click(jsc, x, y):
    for j in jsc.tag['gui_nodes'].values():
        if j['no_context_menu']:
            continue

        if abs(x - j['x_render']) < j['icon_radius']:
            if abs(y - j['y_render']) < j['icon_radius']:

                html = ''

                print(jsc.tag.keys())


                details = jsc.tag['config']['jobs'][j['name']]

#                details = jsc.tag['FlowControllerJobsSnapshot']._job_dict[j['name']]
                for k in sorted(details.keys()):
                    html += f'<span style="color: steelblue">{k} :</span> {details[k]}\n'

                jsc.eval_js_code(blocking=False, js_code=f"""$('#pre_status').html(`{html}`)""")

                msg = SMQC.construct_msg('request_log_chunk', jsc.tag['cfg_uid'], {'job_name': j['name'], 'range': ''})
                response = SMQC.send_message(msg, wait=5)
                s = response['log']
#                 print(response)
# 
#                 log_filename = jsc.tag['FlowControllerJobsSnapshot'].get_log_filename(j['name'])
#                 if os.path.exists(log_filename):
#                     with open(log_filename, 'r') as f:
#                         s = f.read()
#                     s = log_filename + "\n-----\n" + s

#                 else:
#                     s = f"<span style='color:red'>This job may not have run for today yet.</span>\n\nlog file at {log_filename} does not exist."
                jsc.eval_js_code(blocking=False, js_code=f"""$('#pre_log').html(`{s}`)""")

                return


def close(jsc):
    pass
    
#    print('CLOSE', args, kwargs)


def context_menu_request_show(jsc, x, y, page_x, page_y):
    for j in jsc.tag['gui_nodes'].values():
        if j['no_context_menu']:
            continue

        if abs(x - j['x_render']) < j['icon_radius']:
            if abs(y - j['y_render']) < j['icon_radius']:
                jsc.eval_js_code(blocking=False, js_code=f"contextMenuShow({page_x}, {page_y}, \"{j['name']}\");")
                return


def heartbeat_callback():
    for jsc in get_all_jsclients():
        # if the jsc does not have FlowControllerInfo we don't need to process a heartbeat            
        if 'FlowControllerInfo' not in jsc.tag or jsc.tag['FlowControllerInfo'] is None:
            continue

        # check if the FlowControllerRPC is alive
        try:
            jsc.tag['FlowControllerRPC'].is_alive()
        except Exception as e:
            jsc.eval_js_code(blocking=False, js_code="show_no_connection();")


def ready_cfg_view(jsc, *args):
    # make sure required params are present
    if args[2].startswith('?'):
        params = parse_qs(args[2][1:])
        if 'CFG_UID' not in params:
            jsc.eval_js_code(blocking=False, js_code=f"window.location.replace('/');")

    html = ''
    for state in [JobState.IDLE, JobState.PENDING, JobState.RUNNING, JobState.SUCCESS, JobState.FAILURE]:
        html += f"""<span class="dot" style="background-color: {COLOR_MAPPING[state]}"></span>{state.name}<br>"""

    jsc.eval_js_code(blocking=False, js_code=f"$('#legend').html(`{html}`)")

    reconnect(jsc, *args)
    jsc.eval_js_code(blocking=False, js_code="canvasViewportAutofit(gBoundingBox)")
    if jsc.user is not None:
        jsc.eval_js_code(blocking=False, js_code="$('#btn_login').css('display', 'none')")
        jsc.eval_js_code(blocking=False, js_code=f"$('#btn_logout').html('Logout<br><br>{jsc.user.decode()}')")
        jsc.eval_js_code(blocking=False, js_code="$('#btn_logout').css('display', 'inline-block')")
    else:
        jsc.eval_js_code(blocking=False, js_code="$('#btn_login').css('display', 'inline-block')")
        jsc.eval_js_code(blocking=False, js_code="$('#btn_logout').css('display', 'none')")
        jsc.eval_js_code(blocking=False, js_code="$('#btn_logout').html('Logout')")
        jsc.eval_js_code(blocking=False, js_code="$('#adminMenu').addClass('disabled')")
        jsc.eval_js_code(blocking=False, js_code="$('#contextMenu').addClass('disabled')")


def ready_index(jsc, *args):
    reconnect(jsc, *args)


def ready(jsc, *args):
    if args[1].startswith('/cfg_view.html'):
        return ready_cfg_view(jsc, *args)
    if args[1].startswith('/'):
        return ready_index(jsc, *args)

def reconnect_cfg_view(jsc, *args):
    jsc.tag['url_args'] = args
    jsc.tag['url_params'] = {}
    if args[2].startswith('?'):
        jsc.tag['url_params'] = parse_qs(args[2][1:])
        
#    cfg_uid = jsc.tag['url_params']['CFG_UID'][0]
    jsc.tag['cfg_uid'] = jsc.tag['url_params']['CFG_UID'][0]

    all_info = SMQC.get_info_for_all_clients()
    found = False
    for k, v in all_info.items():
        if 'FlowController' in v['classifications']:
            if k == jsc.tag['cfg_uid'] and ('FlowController' in v['classifications']):
                found = True
                break
    
            
#     controllers = FlowController.discover_all_flow_controllers('localhost:6500')
#     jsc.tag['FlowControllerInfo'] = None
#     for c in controllers:
#         print(c['cfg_uid'])
#         if c['cfg_uid'] == jsc.tag['url_params']['CFG_UID'][0]:
#             jsc.tag['FlowControllerInfo'] = c

#    if jsc.tag['FlowControllerInfo'] is None:
    if not found:
        
        # clear the canvas and just show an error message
        js = f"""
            console.log(gCanvas.width);
            gCtx.textBaseline = "middle";
            gCtx.setTransform();
            gCtx.fillStyle = "#FFE0E0";
            $('#title').css('background-color', '#FFE0E0');
            $('#title').html('No Flow Controller Configuration found for "{jsc.tag['url_params']['CFG_UID'][0]}"');
            gCtx.clearRect(0, 0, gCanvas.width, gCanvas.height);
            gCtx.fillRect(0, 0, gCanvas.width, gCanvas.height);
        """
        jsc.eval_js_code(blocking=False, js_code=js)
        return

#    jsc.tag['FlowControllerRPC'] = FlowControllerRPCClient(jsc.tag['FlowControllerInfo']['rpc_addr'])

    try:
        response = SMQC.send_message(SMQC.construct_msg('request_icon', jsc.tag['cfg_uid'], {}), wait=5)
        jsc.tag['icon'] = response['icon']
    except:
        jsc.tag['icon'] = ''



    refresh_gui_nodes(jsc)
    redraw_canvas(jsc)


def reconnect_index(jsc, *args):
    print(SMQC)
    flow_controllers = []
    all_info = SMQC.get_info_for_all_clients()
    for k, v in all_info.items():
        if 'FlowController' in v['classifications']:
            flow_controllers.append(v)
            
#    controllers = FlowController.discover_all_flow_controllers('localhost:6500')
    jsc.tag['FlowControllerInfo'] = None

    html = ''    
    for c in flow_controllers:
#        print(c.keys())
        html += f"""<a class=button1 target="_blank" style='position: static; margin-top:10px' href='/cfg_view.html?CFG_UID={c['client_name']}'>{c['client_name']}</a> <span class=desc><i>{c['client_name']}</i></span><br>"""
    
    jsc['#picklist'].html = html 
    
    
    print('RECONNECT INDEX')
    pass 


def reconnect(jsc, *args):
    print('reconnect ', args)
    if args[1].startswith('/cfg_view.html'):
        return reconnect_cfg_view(jsc, *args)
    if args[1].startswith('/'):
        return reconnect_index(jsc, *args)
    print(args)


def refresh_gui_nodes(jsc):
    response = SMQC.send_message(SMQC.construct_msg('request_config', jsc.tag['cfg_uid'], {}), wait=5)
    config = response['config']
    jsc.tag['config'] = config
    
    
    
    
    
#    print(config)
    
#    jsc.tag['FlowControllerJobsSnapshot'] = jsc.tag['FlowControllerRPC'].get_jobs_snapshot()

    # load the logo
    try:
#        icon = base64.b64encode(jsc.tag['FlowControllerJobsSnapshot'].get_logo().data)
        icon = "data:image/png;base64," + jsc.tag['icon']
        jsc.eval_js_code(blocking=False, js_code=f"""gLogoImg.src = '{icon}';""")
    except Exception as e:
        print(e)

    jsc.eval_js_code(blocking=False, js_code=f"""$('#title').html("{config['title']}");""")

    jsc.tag['gui_nodes'] = _convert_cfg_to_gui_nodes(config)


def redraw_canvas(jsc):
    print('redraw canvas')
    js = """
        gCtx.textBaseline = "middle";
        gBoundingBox = [0, 0, 0, 0];
        var oldtransform = gCtx.getTransform();
        gCtx.setTransform();
        gCtx.fillStyle = "#F8F8F8";
        gCtx.clearRect(0, 0, gCanvas.width, gCanvas.height);
        gCtx.fillRect(0, 0, gCanvas.width, gCanvas.height);

        var wh = Math.min(gCanvas.width, gCanvas.height) * 0.85;
        gCtx.globalAlpha = 0.2;
        try {
            gCtx.drawImage(gLogoImg, (gCanvas.width - wh) / 2, (gCanvas.height - wh) / 2, wh, wh);
        } catch(err) {
        }
        gCtx.globalAlpha = 1;

        gCtx.setTransform(oldtransform);
    """
    for j in jsc.tag['gui_nodes'].values():
        js += _generate_draw_job_node_js(jsc, j)

    js = f"""
        gJSCanvasFrame = `{js}`;
        eval(gJSCanvasFrame);
        """

    jsc.eval_js_code(blocking=False, js_code=js)


# def message_handler(smq_uid, msg, msg_data):
#     try:
#         if msg == 'FlowController.Changed':
#             print(msg)
#             for jsc in get_all_jsclients():
#                 # TODO: we should decide this based on the page url in the jsc not beased on existence of this property
#                 if 'FlowControllerInfo' in jsc.tag:
#                     if jsc.tag['FlowControllerInfo']:
#                         if jsc.tag['FlowControllerInfo']['cfg_uid'] == msg_data:
#                             refresh_gui_nodes(jsc)
#                             redraw_canvas(jsc)
#     except Exception:
#         logging.error(traceback.format_exc())


def on_job_state_changed(msg, smc):
    for jsc in get_all_jsclients():
        if jsc.tag.get('cfg_uid', None) == msg['sender_id']:
            refresh_gui_nodes(jsc)
            redraw_canvas(jsc)

def on_config_changed(msg, smqc):
    for jsc in get_all_jsclients():
        if jsc.tag.get('cfg_uid', None) == msg['sender_id']:
            refresh_gui_nodes(jsc)
            redraw_canvas(jsc)

# --------------------------------------------------
#    Main
# --------------------------------------------------
def run(args):
    global SMQC


 #       client_uid = self.get_client_id()
 #       classifications = ['FlowController', client_uid]
 #       pub_list = ['job_log_changed', 'job_state_changed']
 #       sub_list = ['change_job_state', 'reload_config', 'request_config', 'request_icon', 'request_log_chunk',
 #                   'trigger_job']
    SMQC = SMQ_Client('http://' + args['smq_server'], 'Flow Controller WebApp', 'Flow Controller WebApp', ['WebApp'], [], [])
#            self._job_manager.get_config_prop('smq_server'), client_uid, client_uid, classifications, pub_list, sub_list)


    SMQC.add_message_handler('config_changed', on_config_changed)
    SMQC.add_message_handler('job_state_changed', on_job_state_changed)

    
#    SMQC = SMQClient()
    try:
        SMQC.start()
#        SMQC.start_client(args['smq_server'], 'Flow Controller WebApp', 'FlowController.Trigger', 'FlowController.Changed', message_handler)
        
    except ConnectionRefusedError:
        SMQC = None
        logging.error('SMQ Server is not running!')

    signal.signal(signal.SIGTERM, lambda a, b: SMQC.shutdown())
    signal.signal(signal.SIGINT, lambda a, b: SMQC.shutdown())
    

    login_html_page = os.path.join(os.path.dirname(__file__), 'flow_controller_login.html')
    default_html_page = os.path.join(os.path.dirname(__file__), 'flow_controller_webapp_index.html')

    run_pylinkjs_app(default_html=default_html_page, port=7010, login_html_page=login_html_page,
                     html_dir=os.path.dirname(__file__), onContextClose=close,
                     heartbeat_callback=heartbeat_callback, heartbeat_interval=10)


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG, format='%(asctime)s %(levelname)s %(threadName)s %(message)s')
    logging.info('Flow Controller WebApp Started')

    try:
        # parse the arguments
        parser = argparse.ArgumentParser(description='Flow Controller WebApp')
        parser.add_argument('--smq_server', default='localhost:6050')
        args = parser.parse_args()

        # run
        run(vars(args))
    except Exception:
        logging.error(traceback.format_exc())
    finally:
        logging.info('Flow Controller WebApp Exiting')
