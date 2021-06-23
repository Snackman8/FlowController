
/* --------------------------------------------------
    Globals
-------------------------------------------------- */
var gCanvasViewPortCanvas;
var gCanvasViewPortCtx;
var gCanvasViewportPanning = false;
var gCanvasViewportPanningOrigin = [0, 0];
var gCanvasViewportRefreshHandler;
var gCanvasViewPortZoom = 1.0;


function canvasViewportInit(canvasId, refreshHandler) {
    // initialize listeners
    gCanvasViewportRefreshHandler = refreshHandler;
    gCanvasViewPortCanvas = document.getElementById(canvasId);
    gCanvasViewPortCtx = gCanvasViewPortCanvas.getContext("2d");
    gCanvasViewPortCanvas.addEventListener("mousedown", canvasViewportMousedown);
    gCanvasViewPortCanvas.addEventListener("mousemove", canvasViewportMousemove);
    gCanvasViewPortCanvas.addEventListener("mouseup", canvasViewportMouseup);
    gCanvasViewPortCanvas.addEventListener("mousewheel", canvasViewportMousewheel);
}


function canvasViewportAutofit(boundingbox) {
    // calculate zoom based on aspect ratio
    var bh = (boundingbox[3] - boundingbox[1]);
    var bw = (boundingbox[2] - boundingbox[0]);
    gCanvasViewPortZoom = Math.min(gCanvasViewPortCanvas.width / bw, gCanvasViewPortCanvas.height / bh) * 0.9;
    
    // center the bounding box and redraw    
    gCanvasViewPortCtx.setTransform();
    gCanvasViewPortCtx.clearRect(0, 0, gCanvasViewPortCanvas.width, gCanvasViewPortCanvas.height);
    gCanvasViewPortCtx.translate((gCanvasViewPortCanvas.width - bw * gCanvasViewPortZoom) / 2,
                                 (gCanvasViewPortCanvas.height - bh * gCanvasViewPortZoom) / 2);
    gCanvasViewPortCtx.scale(gCanvasViewPortZoom, gCanvasViewPortZoom);
    gCanvasViewportRefreshHandler(); 
}


function canvasViewportMousedown(e) {
    // set panning flag and save panning origin
    var currentTransform = gCanvasViewPortCtx.getTransform();
    gCanvasViewportPanning = true;
    gCanvasViewportPanningOrigin = [-currentTransform.e + e.offsetX, -currentTransform.f + e.offsetY];
}


function canvasViewportMousemove(e) {
    if (gCanvasViewportPanning) {
        var oldtransform = gCanvasViewPortCtx.getTransform();
        gCanvasViewPortCtx.setTransform();
        gCanvasViewPortCtx.clearRect(0, 0, gCanvasViewPortCanvas.width, gCanvasViewPortCanvas.height);
        gCanvasViewPortCtx.setTransform(
            gCanvasViewPortZoom, 0, 0, gCanvasViewPortZoom,
            e.offsetX - gCanvasViewportPanningOrigin[0],
            e.offsetY - gCanvasViewportPanningOrigin[1]);
        gCanvasViewportRefreshHandler(); 
    }
}


function canvasViewportMouseup(e) {
    // clear the panning flag
    gCanvasViewportPanning = false;
}


function canvasViewportMousewheel(e) {
    var oldtransform = gCanvasViewPortCtx.getTransform();
    var oldZoom = gCanvasViewPortZoom;

    if (e.wheelDelta < 0) {
        gCanvasViewPortZoom = gCanvasViewPortZoom / 1.1;
    } else {
        gCanvasViewPortZoom = gCanvasViewPortZoom * 1.1;
    }

    gCanvasViewPortCtx.setTransform();
    gCanvasViewPortCtx.clearRect(0, 0, gCanvasViewPortCanvas.width, gCanvasViewPortCanvas.height);
    gCanvasViewPortCtx.scale(gCanvasViewPortZoom, gCanvasViewPortZoom);
    gCanvasViewPortCtx.translate(e.offsetX / gCanvasViewPortZoom - (e.offsetX - oldtransform.e) / oldZoom,
                                 e.offsetY / gCanvasViewPortZoom - (e.offsetY - oldtransform.f) / oldZoom);

    gCanvasViewportRefreshHandler();
    e.preventDefault();
}


function canvasViewportOffsetXYToAbsoluteXY(x, y) {
    var currentTransform = gCanvasViewPortCtx.getTransform();
    
    return [(x - currentTransform.e) / currentTransform.a,
            (y - currentTransform.f) / currentTransform.d];
}