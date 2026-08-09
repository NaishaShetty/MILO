"""
vision/visualization

Purpose
-------
Home for rendering a `Scene` (boxes, masks, labels, confidences) onto
its source RGB image, e.g. for saving annotated frames like
`outputs/annotated_scene.png`. Kept separate from the detectors and
segmenters themselves so that inference code never depends on OpenCV
drawing calls -- perception modules produce data, this package only
renders it.

Contents
--------
- `base_visualizer.BaseVisualizer` -- the `process(image, scene)`
  interface every visualizer implements.
- `scene_visualizer.SceneVisualizer` -- the concrete OpenCV renderer
  used today.

This drawing logic used to live inline in `test_detector.py`
(`cv2.rectangle`/`cv2.putText` calls in the test itself). It moved
here once a second caller (mask rendering, and this phase's dedicated
test) needed the same drawing, so it isn't duplicated.
"""
