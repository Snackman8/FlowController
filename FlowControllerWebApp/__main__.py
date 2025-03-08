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
from pylinkjs.plugins.authGoogleOAuth2Plugin import pluginGoogleOAuth2
from pylinkjs.plugins.authDevAuthPlugin import pluginDevAuth
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

        # handle every x minutes
        if f[0].startswith('*/') and f[1] == '*':
            retval += f"every {f[0][2:]} mins "

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
        'parent_curve_settings': [],
        'dependency_line_after_text': True}

    # copy the default values
    gn = dict(j)
    for k, v in defaults.items():
        if k not in gn:
            gn[k] = v

    # if no depends, then we don't show an icon
    if not gn['depends']:
        gn['icon_shape'] = j.get('icon_shape', 'none')
        gn['no_context_menu'] = j.get('no_context_menu', True)

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


def _generate_draw_job_node_js(node_info):
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
            if p['dependency_line_after_text']:
                sx = f"""({p['x_rendertext']} + gCtx.measureText(t).width + {p['text_padding_left']} + {p['text_padding_right']})"""
            else:
                sx = f"""({p['x_render']})"""
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


def _update_status_and_log(jsc, job_name):
    jsc.tag['current_job_selected'] = job_name
    msg = SMQC.construct_msg('request_log_chunk', jsc.tag['cfg_uid'], {'job_name': job_name, 'range': ''})
    response = SMQC.send_message(msg, wait=5)
    response_log = response['log'].replace('`', '\`')
    jsc.eval_js_code(blocking=False, js_code=f"""$('#pre_log').html(`{response_log}`); $('#pre_log').scrollTop($('#pre_log')[0].scrollHeight)""")

    response = SMQC.send_message(SMQC.construct_msg('request_config', jsc.tag['cfg_uid'], {}), wait=5)
    jsc.tag['config'] = response['config']

    html = ''
    details = jsc.tag['config']['jobs'][job_name]
    for k in sorted(details.keys()):
        html += f'<span style="color: steelblue">{k} :</span> {details[k]}\n'

    jsc.eval_js_code(blocking=False, js_code=f"""$('#pre_status').html(`{html}`)""")


# --------------------------------------------------
#    Javascript Callbacks
# --------------------------------------------------
def admin_menu_click(jsc, item_text):
    if item_text == 'Index Page':
        jsc.eval_js_code(blocking=False, js_code="""window.location.href = "/";""")

    if item_text == 'Reload Config':
        SMQC.send_message(SMQC.construct_msg('reload_config', jsc.tag['cfg_uid'], {}))

    if item_text == 'Autofit':
        jsc.eval_js_code(blocking=False, js_code="""$('#btn_autofit').click()""")

    if item_text == 'Refresh':
        reconnect_cfg_view(jsc, *jsc.tag['url_args'])


def context_menu_click(jsc, item_text, job_name):
    if item_text == 'Trigger Job':
        SMQC.send_message(SMQC.construct_msg('trigger_job', jsc.tag['cfg_uid'],
                                             {'job_name': job_name,
                                              'reason': f'manually set by user {jsc.user_auth_username}'}))
        refresh_status_and_log = True

    if item_text == 'Set as Ready':
        SMQC.send_message(SMQC.construct_msg('change_job_state', jsc.tag['cfg_uid'],
                                             {'job_name': job_name, 'new_state': 'IDLE',
                                              'reason': f'manually set by user {jsc.user_auth_username}'}))
        refresh_status_and_log = True

    if item_text == 'Set as Success':
        SMQC.send_message(SMQC.construct_msg('change_job_state', jsc.tag['cfg_uid'],
                                             {'job_name': job_name, 'new_state': 'SUCCESS',
                                              'reason': f'manually set by user {jsc.user_auth_username}'}))
        refresh_status_and_log = True

    if item_text == 'Set as Fail':
        SMQC.send_message(SMQC.construct_msg('change_job_state', jsc.tag['cfg_uid'],
                                             {'job_name': job_name, 'new_state': 'FAILURE',
                                              'reason': f'manually set by user {jsc.user_auth_username}'}))
        refresh_status_and_log = True

    if refresh_status_and_log:
        _update_status_and_log(jsc, job_name)


def canvas_click(jsc, x, y):
    for j in jsc.tag['gui_nodes'].values():
        if j['no_context_menu']:
            continue

        if abs(x - j['x_render']) < j['icon_radius']:
            if abs(y - j['y_render']) < j['icon_radius']:
                _update_status_and_log(jsc, j['name'])
                return


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
        # if the jsc does not have cfg_uid we don't need to process a heartbeat
        if 'cfg_uid' not in jsc.tag:
            continue

        # check if the FlowControllerRPC is alive
        try:
            if not SMQC.is_alive(jsc.tag['cfg_uid']):
                raise Exception('Dead')
            jsc.eval_js_code(blocking=False, js_code="clear_no_connection();")
        except Exception as _:
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

    reconnect_cfg_view(jsc, *args)
    jsc.eval_js_code(blocking=False, js_code="canvasViewportAutofit(gBoundingBox)")
    if jsc.user_auth_username is not None:
        jsc.eval_js_code(blocking=False, js_code="$('#btn_login').css('display', 'none')")
        jsc.eval_js_code(blocking=False, js_code=f"$('#btn_logout').html('Logout<br><br>{jsc.user_auth_username}')")
        jsc.eval_js_code(blocking=False, js_code="$('#btn_logout').css('display', 'inline-block')")
    else:
        jsc.eval_js_code(blocking=False, js_code="$('#btn_login').css('display', 'inline-block')")
        jsc.eval_js_code(blocking=False, js_code="$('#btn_logout').css('display', 'none')")
        jsc.eval_js_code(blocking=False, js_code="$('#btn_logout').html('Logout')")
        jsc.eval_js_code(blocking=False, js_code="$('#adminMenu').addClass('disabled')")
        jsc.eval_js_code(blocking=False, js_code="$('#contextMenu').addClass('disabled')")

    # request a resize because logout button has changed size
    jsc.eval_js_code(blocking=False, js_code="onDragEndHandler();")


def ready_index(jsc, *args):
    reconnect_index(jsc, *args)


def ready(jsc, *args):
    if args[1].startswith('/cfg_view.html'):
        return ready_cfg_view(jsc, *args)
    if args[1].startswith('/'):
        return ready_index(jsc, *args)


def reconnect(jsc, *args):
    """ called by pylinkjs when browser reconnects if failed network connection or webapp is restarted """
    if len(args) == 0:
        return reconnect_cfg_view(jsc, *args)

    if args[1].startswith('/cfg_view.html'):
        return reconnect_cfg_view(jsc, *args)
    if args[1].startswith('/'):
        return reconnect_index(jsc, *args)


def reconnect_cfg_view(jsc, *args):
    jsc.tag['url_args'] = args
    jsc.tag['url_params'] = {}
    if args[2].startswith('?'):
        jsc.tag['url_params'] = parse_qs(args[2][1:])
    jsc.tag['cfg_uid'] = jsc.tag['url_params']['CFG_UID'][0]

    all_info = SMQC.get_info_for_all_clients()
    found = False
    for k, v in all_info.items():
        if 'FlowController' in v['classifications']:
            if k == jsc.tag['cfg_uid'] and ('FlowController' in v['classifications']):
                found = True
                break

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

    try:
        response = SMQC.send_message(SMQC.construct_msg('request_icon', jsc.tag['cfg_uid'], {}), wait=5)
        icon = "data:image/png;base64," + response['icon']
        jsc.eval_js_code(blocking=False, js_code=f"""gLogoImg.src = '{icon}';""")
    except Exception as _:
        jsc.tag['icon'] = ''

    refresh_gui_nodes(jsc)
    redraw_canvas(jsc)


def reconnect_index(jsc, *_args):
    flow_controllers = []
    all_info = SMQC.get_info_for_all_clients()
    for v in all_info.values():
        if 'FlowController' in v['classifications']:
            flow_controllers.append(v)

    html = ''
    for c in flow_controllers:
        html += f"""<a class=button1 target="_blank" style='position: static; margin-top:10px'
                    href='/cfg_view.html?CFG_UID={c['client_name']}'>{c['client_name']}</a>
                    <span class=desc><i>{c['tag']['title']}</i></span><br>"""

    jsc['#picklist'].html = html


def refresh_gui_nodes(jsc):
    response = SMQC.send_message(SMQC.construct_msg('request_config', jsc.tag['cfg_uid'], {}), wait=5)
    jsc.tag['config'] = response['config']
    jsc.eval_js_code(blocking=False, js_code=f"""$('#title').html("{jsc.tag['config']['title']}");""")
    jsc.tag['gui_nodes'] = _convert_cfg_to_gui_nodes(jsc.tag['config'])


def redraw_canvas(jsc):
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
        js += _generate_draw_job_node_js(j)

    js = f"""
        gJSCanvasFrame = `{js}`;
        eval(gJSCanvasFrame);
        """
    jsc.eval_js_code(blocking=False, js_code=js)


def on_job_log_changed(msg, _smc):
    for jsc in get_all_jsclients():
        if jsc.tag.get('cfg_uid', None) == msg['sender_id']:
            if jsc.tag.get('current_job_selected', None) == msg['payload']['job_name']:
                _update_status_and_log(jsc, jsc.tag['current_job_selected'])


def on_job_state_changed_or_on_config_changed(msg, _smc):
    for jsc in get_all_jsclients():
        if jsc.tag.get('cfg_uid', None) == msg['sender_id']:
            refresh_gui_nodes(jsc)
            redraw_canvas(jsc)


# --------------------------------------------------
#    Main
# --------------------------------------------------
def run(args):
    global SMQC

    # configure the SMQ Client
    SMQC = SMQ_Client('http://' + args['smq_server'], 'Flow Controller WebApp', 'Flow Controller WebApp', ['WebApp'],
                      ['change_job_state', 'ping', 'reload_config', 'request_config', 'request_icon',
                       'request_log_chunk', 'trigger_job'],
                      ['config_changed', 'job_log_changed', 'job_state_changed'])
    SMQC.add_message_handler('config_changed', on_job_state_changed_or_on_config_changed)
    SMQC.add_message_handler('job_state_changed', on_job_state_changed_or_on_config_changed)
    SMQC.add_message_handler('job_log_changed', on_job_log_changed)
    try:
        SMQC.start()
    except ConnectionRefusedError:
        SMQC = None
        logging.error('SMQ Server is not running!')

    # shutdown the SMQ Client on exit
    signal.signal(signal.SIGTERM, lambda _a, _b: SMQC.shutdown())
    signal.signal(signal.SIGINT, lambda _a, _b: SMQC.shutdown())

    # run the app
    default_html_page = os.path.join(os.path.dirname(__file__), 'flow_controller_webapp_index.html')
    run_kwargs = {}
    run_kwargs['default_html'] = default_html_page
    run_kwargs['port'] = 7010
    run_kwargs['html_dir'] = os.path.dirname(__file__)
    run_kwargs['heartbeat_callback'] = heartbeat_callback
    run_kwargs['heartbeat_interval'] = 1
    run_kwargs['internal_polling_interval'] = 0.05

    # init the auth method
    if args['auth_method'] == 'GoogleOAuth2':
        # init the google oauth2 plugin
        auth_plugin = pluginGoogleOAuth2(client_id=args['oauth2_clientid'],
                                         secret=args['oauth2_secret'],
                                         redirect_url=f'{args["oauth2_redirect_url"]}/login')
    elif args['auth_method'] == 'DevAuth':
        auth_plugin = pluginDevAuth()
    run_kwargs['plugins'] = [auth_plugin]

    # run the application
    run_pylinkjs_app(**run_kwargs)


def console_entry():
    try:
        # parse the arguments
        parser = argparse.ArgumentParser(description='Flow Controller WebApp')
        parser.add_argument('--smq_server', default='localhost:6050')
        parser.add_argument('--logging_level', default='INFO', help='logging level')
        parser.add_argument('--auth_method', help='authentication method', choices=['GoogleOAuth2', 'DevAuth'], default='DevAuth')
        parser.add_argument('--oauth2_clientid', help='google oath2 client id')
        parser.add_argument('--oauth2_redirect_url', help='google oath2 redirect url', default='http://localhost:7010')
        parser.add_argument('--oauth2_secret', help='google oath2 secret')
        args = parser.parse_args()

        # setup logging
        logging.basicConfig(level=logging.getLevelName(args.logging_level),
                            format='%(asctime)s %(levelname)s %(threadName)s %(message)s')
        logging.info('Flow Controller WebApp Started ', vars(args))

        # run
        run(vars(args))
    except Exception:
        logging.error(traceback.format_exc())
    finally:
        logging.info('Flow Controller WebApp Exiting')


if __name__ == "__main__":
    # parse command line arguments
    console_entry()
