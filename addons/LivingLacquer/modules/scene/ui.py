"""Steps 6-8 rows of the Scan Pipeline panel."""
from . import operators


def draw_step(number, layout, context):
    props = context.scene.livinglacquer_props
    if number == 6:
        layout.operator("livinglacquer.pipe_build_scene", text="Build", icon="SCENE_DATA")
        line = operators.status("build")
    elif number == 7:
        row = layout.row(align=True)
        row.operator("livinglacquer.pipe_undistort", text="Undistort", icon="IMAGE_BACKGROUND")
        row.prop(props, "pipe_overwrite", text="", icon="FILE_REFRESH")
        line = operators.status("undistort") or "Runs by itself after Build"
    else:
        layout.operator("livinglacquer.pipe_package", text="Publish to 01.CAM_Photos / 02.Geometry",
                        icon="PACKAGE")
        line = operators.status("package")
    if line:
        layout.label(text=line)
