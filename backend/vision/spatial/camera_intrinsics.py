"""
camera_intrinsics.py

Purpose
-------
Defines `CameraIntrinsics`, a clean, explicit representation of the pinhole
camera model parameters `localization.py` needs to turn a pixel + depth
reading into a 3D point.

Why this exists
----------------
Camera parameters (focal length, principal point, image size) were about
to get hardcoded inside a projection function the first time someone
needed 2D->3D localization. That's exactly the anti-pattern the project
spec calls out: intrinsics change per-camera/per-simulator, projection
math doesn't, so they must not live in the same place. `CameraIntrinsics`
is a plain, explicit data holder; nothing in this file does any 3D math.

Where the numbers come from (AI2-THOR)
-----------------------------------------
AI2-THOR's `Controller` is constructed with a fixed `fieldOfView` (90
degrees, set once in `simulator/ai2thor_env.py` and never changed
per-frame) and a fixed `width`/`height`. AI2-THOR does not expose a
focal-length/principal-point pair directly, so `from_ai2thor_fov` derives
a standard pinhole approximation from the vertical field of view:

    fy = (height / 2) / tan(fov / 2)
    fx = fy                              (square pixels assumed)
    cx = width / 2, cy = height / 2      (principal point at image center)

This assumes square pixels and zero lens distortion, which AI2-THOR's
virtual camera satisfies exactly (it is a synthetic renderer, not a real
lens) -- unlike a real camera, no calibration procedure is needed or
possible here. If this project ever localizes objects from a real camera
feed, intrinsics would come from an actual calibration (e.g. checkerboard
+ OpenCV `calibrateCamera`) instead of this constructor, but the
`CameraIntrinsics` shape and everything downstream of it stays identical.
"""

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class CameraIntrinsics:
    """Pinhole camera intrinsic parameters, in pixel units.

    Attributes:
        fx: Focal length along the image x-axis, in pixels.
        fy: Focal length along the image y-axis, in pixels.
        cx: Principal point x-coordinate, in pixels.
        cy: Principal point y-coordinate, in pixels.
        width: Image width, in pixels.
        height: Image height, in pixels.
    """

    fx: float
    fy: float
    cx: float
    cy: float
    width: int
    height: int

    @classmethod
    def from_ai2thor_fov(
        cls, width: int, height: int, fov_degrees: float = 90.0
    ) -> "CameraIntrinsics":
        """Builds intrinsics from AI2-THOR's `Controller(fieldOfView=...)`.

        Args:
            width: `Controller(width=...)` value used to start the sim.
            height: `Controller(height=...)` value used to start the sim.
            fov_degrees: `Controller(fieldOfView=...)` value used to start
                the sim (AI2-THOR's default/this project's convention is
                90 degrees -- see `simulator/ai2thor_env.py`).

        Returns:
            A `CameraIntrinsics` approximating AI2-THOR's virtual camera
            (square pixels, zero distortion, principal point centered --
            see module docstring for why these hold exactly for AI2-THOR).
        """

        fov_radians = math.radians(fov_degrees)

        fy = (height / 2.0) / math.tan(fov_radians / 2.0)
        fx = fy

        return cls(
            fx=fx,
            fy=fy,
            cx=width / 2.0,
            cy=height / 2.0,
            width=width,
            height=height,
        )
