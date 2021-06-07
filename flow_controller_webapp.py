# --------------------------------------------------
#    Imports
# --------------------------------------------------
import logging
import traceback
import argparse
import time
from pylinkjs.PyLinkJS import run_pylinkjs_app, get_all_jsclients
from flow_controller import FlowController, FlowControllerJobs
from smq import SMQClient
import atexit
import xmlrpc


# --------------------------------------------------
#    Global Variables
# --------------------------------------------------
SMQC = None

COLOR_MAPPING = {
    'SUCCESS': 'green',
    'FAIL': 'red',
    }


# --------------------------------------------------
#    Private Functions
# --------------------------------------------------
def _convert_job_to_guinode(j):
    # default values for gui nodes
    defaults = {
        'width': 200,
        'depends': [],
        'x': 0,
        'y': 0,
        'x_offset': 0,
        'y_offset': 0,
        'icon_radius': 8,
        'text_color': '#000000',
        'text_padding_left': 4,
        'text_padding_right': 4,
        'icon_shape': 'circle',
        'parent_curve_settings': []}

    # copy the default values
    gn = dict(j)
    for k, v in defaults.items():
        if k not in gn:
            gn[k] = v

    # set some derived values
    gn['children'] = []
    gn['children_rendered'] = []
    gn['parents'] = []
    gn['text'] = gn.get('text', gn['name'])

    job_state = gn.get('job_state', '?')
    gn['icon_color'] = COLOR_MAPPING.get(job_state, 'gainsboro')    

    # success!
    return gn


def _convert_cfg_to_gui_nodes(cfg):
    # convert the cfg nodes to gui nodes
    fcj = FlowControllerJobs()
    fcj.load_from_existing_cfg(cfg['_cfg'])
    jobs = fcj.get_jobs()    

    gui_jobs = [_convert_job_to_guinode(j) for j in jobs]
    gui_jobs = {j['name']: j for j in gui_jobs}

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
                j['x'] = j['parents'][0]['x_render'] + j['width']
                j['y'] = j['parents'][0]['y_render'] + (len(j['parents'][0]['children_rendered']) - (len(j['parents'][0]['children']) - 1) / 2.0) * 30
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
    js = f"""
        gCtx.beginPath();
        gCtx.strokeStyle = "{node_info['icon_color']}";
        gCtx.fillStyle = "{node_info['icon_color']}";
        gCtx.arc({node_info['x_render']}, {node_info['y_render']}, {node_info['icon_radius']}, 0, Math.PI * 2, true);
        gCtx.stroke();
        gCtx.fill();
        gCtx.fillStyle = "{node_info['text_color']}";
        gCtx.fillText("{node_info['text']}", {node_info['x_rendertext'] + node_info['text_padding_left']}, {node_info['y_render']});

        if (({node_info['x_render']} - {node_info['icon_radius']}) < gBoundingBox[0]) {{
            gBoundingBox[0] = ({node_info['x_render']} - {node_info['icon_radius']});
        }}

        if (({node_info['y_render']} - {node_info['icon_radius']}) < gBoundingBox[1]) {{
            gBoundingBox[1] = ({node_info['y_render']} - {node_info['icon_radius']});
        }}

        if (({node_info['x_rendertext']} + gCtx.measureText("{node_info['text']}").width + {node_info['text_padding_left']}) > gBoundingBox[2]) {{
            gBoundingBox[2] = ({node_info['x_rendertext']} + gCtx.measureText("{node_info['text']}").width + {node_info['text_padding_left']});
        }}

        if (({node_info['y_render']} + {node_info['icon_radius']}) > gBoundingBox[3]) {{
            gBoundingBox[3] = ({node_info['y_render']} + {node_info['icon_radius']});
        }}
    """

    if node_info['parents'] is not None:
        for i, p in enumerate(node_info['parents']):
            pc = node_info['parent_curve_settings'][i]
            sx = f"""({p['x_rendertext']} + gCtx.measureText("{p['text']}").width + {node_info['text_padding_left']})"""
            sy = f"""({p['y_render']})"""
            ex = f"""({node_info['x_render'] - node_info['icon_radius']})"""
            ey = f"""({node_info['y_render']})"""
            cx1 = f"""({sx} + ({ex} - {sx}) * {pc[0][0]})"""
            cy1 = f"""({sy} + ({ey} - {sy}) * {pc[0][1]})"""
            cx2 = f"""({sx} + ({ex} - {sx}) * {pc[1][0]})"""
            cy2 = f"""({sy} + ({ey} - {sy}) * {pc[1][1]})"""
            js += f"""
            gCtx.beginPath();
            gCtx.strokeStyle = "{p['icon_color']}";
            gCtx.moveTo({sx}, {sy});
            gCtx.bezierCurveTo({cx1}, {cy1}, {cx2}, {cy2}, {ex}, {ey});
            gCtx.stroke();
            """

    return js


# --------------------------------------------------
#    Javascript Callbacks
# --------------------------------------------------
def context_menu_click(jsc, item_text, job_name):
    if item_text == 'Trigger':
#        cfg_uid = jsc.tag['cfg']['_cfg']['uid']

        print('CONTEXT')


        FlowController.trigger_job_rpc(jsc.tag['FlowControllerInfo']['rpc_addr'], job_name)

#         print(jsc.tag['FlowControllerInfo'])
#         
#         SMQC.publish_message('FlowController.Trigger', {'cfg_uid': cfg_uid, 'job_name': job_name})
    if item_text == 'Reset':
        FlowController.set_job_state_rpc(jsc.tag['FlowControllerInfo']['rpc_addr'], job_name, 'FAIL')
#        pass
#         cfg_uid = jsc.tag['cfg']['_cfg']['uid']
#         SMQC.publish_message('FlowController.SetState', {'cfg_uid': cfg_uid, 'job_name': job_name, 'new'})
#     print(item_text, job_name)


def context_menu_request_show(jsc, x, y, page_x, page_y):
    for j in jsc.tag['gui_nodes'].values():
        if abs(x - j['x_render']) < j['icon_radius']:
            if abs(y - j['y_render']) < j['icon_radius']:
                jsc.eval_js_code(blocking=False, js_code=f"contextMenuShow({page_x}, {page_y}, \"{j['name']}\");")
                return


def ready(jsc, *args):
    # convert URL query string to dict
    reconnect(jsc)
    jsc.eval_js_code(blocking=False, js_code="canvasViewportAutofit(gBoundingBox)")

def reconnect(jsc, *args):
    jsc.tag['url_params'] = {}
    query_string = jsc.eval_js_code(blocking=True, js_code="window.location.search")
    if query_string.startswith('?'):
        query_string = query_string[1:]
        for param in query_string.split('&'):
            key, _, value = param.partition('=')
            jsc.tag['url_params'][key] = value
    controllers = FlowController.discover_all_flow_controllers('localhost:6500')
    for c in controllers:
        if c['cfg_uid'] == jsc.tag['url_params']['CFG_UID']:
            jsc.tag['FlowControllerInfo'] = c

    jsc.tag['cfg'] = FlowController.get_cfg_rpc(jsc.tag['FlowControllerInfo']['rpc_addr'])
    jsc.tag['gui_nodes'] = _convert_cfg_to_gui_nodes(jsc.tag['cfg'])

    
    redraw_canvas(jsc)

def redraw_canvas(jsc):
    js = """
        gCtx.textBaseline = "middle";
        gBoundingBox = [0, 0, 0, 0];
        var oldtransform = gCtx.getTransform();
        gCtx.setTransform();
        gCtx.clearRect(0, 0, gCanvas.width, gCanvas.height);
        gCtx.setTransform(oldtransform);
    """
    for j in jsc.tag['gui_nodes'].values():
        js += _generate_draw_job_node_js(jsc, j)

    js = f"""
        gJSCanvasFrame = `{js}`;
        eval(gJSCanvasFrame);
        """

    jsc.eval_js_code(blocking=False, js_code=js)


def message_handler(smq_uid, msg, msg_data):
    try:
        if msg == 'FlowController.Changed':
            for jsc in get_all_jsclients():
                if jsc.tag['cfg']['_cfg']['uid'] == msg_data:
                    jsc.tag['cfg'] = FlowController.get_cfg_rpc(jsc.tag['FlowControllerInfo']['rpc_addr'])
                    jsc.tag['gui_nodes'] = _convert_cfg_to_gui_nodes(jsc.tag['cfg'])
                    
                    redraw_canvas(jsc)
    except Exception:
        logging.error(traceback.format_exc())
    


# --------------------------------------------------
#    Main
# --------------------------------------------------
def run(args):
    global SMQC
    SMQC = SMQClient()
    SMQC.set_message_handler(message_handler)
    try:
        SMQC.start_client(args['smq_server'], 'Flow Controller WebApp', 'FlowController.Trigger', 'FlowController.Changed')
    except ConnectionRefusedError:
        logging.error('SMQ Server is not running!')
 
    atexit.register(lambda: SMQC.shutdown())
    
    run_pylinkjs_app(default_html='flow_controller_webapp.html', port=7010)


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG, format='%(relativeCreated)6d %(threadName)s %(message)s')
    logging.info('Flow Controller WebApp Started')

    try:
        # parse the arguments
        parser = argparse.ArgumentParser(description='Flow Controller WebApp')
        parser.add_argument('--smq_server', default='localhost:6500')
        args = parser.parse_args()

        # run
        run(vars(args))
    except Exception:
        logging.error(traceback.format_exc())
    finally:
        logging.info('Flow Controller WebApp Exiting')





# def _load_config_file(cfg_filename):
#     # load the config file
#     fcj = FlowControllerJobs()
#     fcj.load_from_cfg_file(cfg_filename)
#     jobs = fcj.get_jobs()
# 
#     # convert the cfg nodes to gui nodes
#     gui_jobs = [_convert_job_to_guinode(j) for j in jobs]
#     gui_jobs = {j['name']: j for j in gui_jobs}
# 
#     # repoint the depends to parent gui nodes, and find roots at the same time
#     stack = []
#     for j in gui_jobs.values():
#         if not j['depends']:
#             stack.append(j)
#         else:
#             for pjn in j['depends']:
#                 j['parents'].append(gui_jobs[pjn])
#                 gui_jobs[pjn]['children'].append(j)
# 
#             # fix any missing curve settings
#             for i in range(0, len(j['parents'])):
#                 if len(j['parent_curve_settings']) <= i:
#                     j['parent_curve_settings'].append(None)
#                 if j['parent_curve_settings'][i] is None:
#                     j['parent_curve_settings'][i] = [[0.5, 0], [0.75, 1]]
# 
#     # do our best to traverse the nodes in order, i think it might be ok to be circular sometimes
#     processed = set()
#     for j in gui_jobs.values():
#         if j not in stack:
#             stack.append(j)
#     while stack:
#         j = stack.pop(0)
#         if j['parents']:
#             if j['parents'][0]['name'] in processed:
#                 # parent already processed so we can computer our x and y
#                 j['x'] = j['parents'][0]['x_render'] + j['width']
#                 j['y'] = j['parents'][0]['y_render'] + (len(j['parents'][0]['children_rendered']) - (len(j['parents'][0]['children']) - 1) / 2.0) * 30
#                 j['parents'][0]['children_rendered'].append(j)
#             else:
#                 # parent hasn't been processed yet, so reinsert into the stack
#                 stack.remove(j['parents'][0])
#                 stack.insert(j)
#                 stack.insert(j['parents'][0], 0)
#                 continue
#         processed.add(j['name'])
#         j['x_render'] = j['x'] + j['x_offset']
#         j['y_render'] = j['y'] + j['y_offset']
#         j['x_rendertext'] = j['x_render'] + j['icon_radius'] * 1.5
#         j['y_rendertext'] = j['y_render']
# 
#     return gui_jobs


#     global SMQC
#     global JOBS
#     JOBS = _load_config_file('cfg_signal_test.py')
# 
#     SMQC = SMQClient()
#     try:
#         SMQC.start_client(args['smq_server'], 'Flow Controller WebApp', 'FlowController.Ping', 'FlowController.Pong FlowController.Started')
#     except ConnectionRefusedError:
#         logging.error('SMQ Server is not running!')
# 
#     atexit.register(lambda: SMQC.shutdown())

#    discover()

# def discover():
#     print('Discover!')
#     SMQC.publish_message('FlowController.Ping', '')
#     time.sleep(0.1)
#     while True:
#         msg = SMQC.get_message()
#         print(msg)
#         if msg is None:
#             break
#         print('****', msg)
#         if msg['msg'] == 'FlowController.Pong':
#             rpc_server_address = msg['msg_data']
#             client_uid = msg['client_uid']
#             CFGS[client_uid] = rpc_server_address
# 
#     print('Discover Over!', rpc_server_address)
#     fc = xmlrpc.client.ServerProxy('http://' + rpc_server_address[0] + ':' + str(rpc_server_address[1]), allow_none=True)    
#     
#     print(fc.get_cfg_jobs())
#     
#     
