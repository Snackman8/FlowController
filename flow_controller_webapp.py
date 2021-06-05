# --------------------------------------------------
#    Imports
# --------------------------------------------------
import logging
import traceback
import argparse
from PyLinkJS import run_pylinkjs_app
from flow_controller import FlowControllerJobs


# --------------------------------------------------
#    Global Variables
# --------------------------------------------------
JOBS = {}


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
        'icon_color': 'gainsboro',
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

    # success!
    return gn


def _load_config_file(cfg_filename):
    # load the config file
    fcj = FlowControllerJobs(cfg_filename)
    jobs = fcj.get_jobs()

    # convert the cfg nodes to gui nodes
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
            gCtx.moveTo({sx}, {sy});
            gCtx.bezierCurveTo({cx1}, {cy1}, {cx2}, {cy2}, {ex}, {ey});
            gCtx.stroke();
            """

    return js


# --------------------------------------------------
#    Javascript Callbacks
# --------------------------------------------------
def redraw_canvas(jsc):
    js = """
        gCtx.textBaseline = "middle";
        gBoundingBox = [0, 0, 0, 0];
    """
    for j in JOBS.values():
        js += _generate_draw_job_node_js(jsc, j)

    js = f"""
        gJSCanvasFrame = `{js}`;
        eval(gJSCanvasFrame);
        """

    jsc.eval_js_code(blocking=False, js_code=js)


def ready(jsc, *args):
    redraw_canvas(jsc)
    jsc.eval_js_code(blocking=False, js_code="canvasViewportAutofit(gBoundingBox)")


# --------------------------------------------------
#    Main
# --------------------------------------------------
def run(args):
    global JOBS
    JOBS = _load_config_file('cfg_signal_test.py')

    run_pylinkjs_app(default_html='flow_controller_webapp.html', port=7010)


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG, format='%(relativeCreated)6d %(threadName)s %(message)s')
    logging.info('Flow Controller WebApp Started')

    try:
        # parse the arguments
        parser = argparse.ArgumentParser(description='Flow Controller')
        args = parser.parse_args()

        # run
        run(vars(args))
    except Exception:
        logging.error(traceback.format_exc())
    finally:
        logging.info('Flow Controller WebApp Exiting')
