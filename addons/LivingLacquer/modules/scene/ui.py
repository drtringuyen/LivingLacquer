"""Step 4 - Build Scene & Cameras (build, undistort + camera photos, looking through the cameras) and
step 5 - Package."""
from ..project.ui import big_row
from . import icons, operators, turn


def draw_step(number, layout, context):
    props = context.scene.livinglacquer_props
    if number == 4:
        row = big_row(layout)
        row.operator("livinglacquer.pipe_build_scene", text="4. Build Scene", icon="SCENE_DATA")
        row.operator("livinglacquer.pipe_auto_level", text="", icon="ORIENTATION_GLOBAL")
        person = icons.person_icon()
        if person:
            row.prop(props, "pipe_show_human", text="", icon_value=person, toggle=True)
        else:
            row.prop(props, "pipe_show_human", text="", icon="USER", toggle=True)
        row.prop(props, "pipe_pivot_origin", text="", icon="PIVOT_CURSOR", toggle=True)
        if operators.status("build"):
            layout.label(text=operators.status("build"))

        row = big_row(layout)
        row.operator("livinglacquer.pipe_undistort", text="4. Undistort & Camera Photos", icon="IMAGE_BACKGROUND")
        row.operator("livinglacquer.pipe_undistort", text="", icon="FILE_REFRESH").redo_all = True
        layout.label(text=operators.status("undistort") or "Runs by itself after Build")
        row = layout.row(align=True)
        row.operator("livinglacquer.pipe_turn_cameras", text="Turn Camera Photos", icon="ORIENTATION_GIMBAL")
        layout.label(text=turn.STATUS["text"] or "Stands them like step 2's Photos stand, no new reconstruction")
        _draw_cameras(layout, context, props)
    else:
        big_row(layout).operator("livinglacquer.pipe_package", text="5. Package: Publish", icon="PACKAGE")
        layout.label(text="into 01.CAM_Photos / 02.Geometry, paths relative")
        if operators.status("package"):
            layout.label(text=operators.status("package"))


def _draw_cameras(layout, context, props):
    """Look through the cameras and set how their photos show (was the Metashape panel)."""
    box = layout.box()
    row = box.row(align=True)
    row.operator("livinglacquer.metashape_step_camera", text="", icon="TRIA_LEFT").direction = -1
    row.operator("livinglacquer.metashape_look_through", text="Look Through Camera", icon="VIEW_CAMERA")
    row.operator("livinglacquer.metashape_step_camera", text="", icon="TRIA_RIGHT").direction = 1
    cam = context.scene.camera
    if cam:
        box.label(text=f"Camera: {cam.name}", icon="OUTLINER_OB_CAMERA")
    if props.pipe_pivot_origin:
        box.label(text="Working on the Transform: only the camera looked through shows", icon="INFO")
    row = box.row(align=True)
    row.prop(props, "metashape_bg_alpha", text="Photo opacity", slider=True)
    box.row(align=True).prop(props, "metashape_bg_depth", expand=True)
