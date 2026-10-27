"""Auto Level & Center: place the Transform empty so the scan stands upright in the middle of the scene.

Up = the normal of the plane the cameras lie on (they circle the object), its sign from the cameras'
own up directions; on the Teapot this matches a hand-levelled result within 0.3 deg. When those do
not agree (an iPhone set used as stored: every camera lies on its side) the cameras looking down at
the object decide; on the BatTrang Disk the old rule stood it upside down. The rotation is
the smallest one that brings that normal to +Z (no extra turn about Z). The mesh's bounding-box center
goes to the world origin. The scale is kept. Only the Transform empty changes, never its children."""
import numpy as np
from mathutils import Matrix, Vector

from . import model


def scan_up(cams):
    """Up in scan space (the Transform's local space) from the cameras' local matrices; None if < 3."""
    if len(cams) < 3:
        return None
    pos = np.array([list(c.matrix_basis.translation) for c in cams])
    _, _, vt = np.linalg.svd(pos - pos.mean(0))
    up = Vector(vt[2]).normalized()
    cam_up = sum(((c.matrix_basis.to_3x3() @ Vector((0, 1, 0))).normalized() for c in cams), Vector())
    if abs(up.dot(cam_up)) < 0.25 * len(cams):
        # the cameras' ups do not agree (photos stored sideways / mixed): scans look down at the object
        fwd = sum(((c.matrix_basis.to_3x3() @ Vector((0, 0, -1))).normalized() for c in cams), Vector())
        if abs(up.dot(fwd)) >= 0.25 * len(cams):
            return up if up.dot(fwd) < 0 else -up
    return -up if up.dot(cam_up) < 0 else up


def level(rig, mesh, cams):
    """Set rig's matrix: upright, mesh centered on the origin, scale kept. Returns the tilt that was
    corrected in degrees, or None when there are too few cameras."""
    up = scan_up(cams)
    if up is None:
        return None
    rot = up.rotation_difference(Vector((0, 0, 1))).to_matrix().to_4x4()
    s = rig.matrix_world.to_scale()
    scale = Matrix.Diagonal((s.x, s.y, s.z, 1.0))
    center = Vector((0, 0, 0))
    if mesh is not None:
        local = model.sample_vertices(mesh, 20000)                 # mesh space
        m = np.array(rot @ scale @ mesh.matrix_basis)               # mesh space -> world (before moving)
        pts = (np.c_[local, np.ones(len(local))] @ m.T)[:, :3]
        center = Vector(((pts.min(0) + pts.max(0)) / 2).tolist())
    rig.matrix_world = Matrix.Translation(-center) @ rot @ scale
    rig["ll_levelled"] = True
    return round(float(np.degrees(up.angle(Vector((0, 0, 1))))), 1)


def is_fresh(rig):
    """Never levelled and still where Build put it (identity): safe to level without asking."""
    return not rig.get("ll_levelled") and rig.matrix_world == Matrix.Identity(4)


