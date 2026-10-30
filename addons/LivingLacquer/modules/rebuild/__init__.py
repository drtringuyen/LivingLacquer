"""Rebuild: step 5 of the scan pipeline, Mesh Rebuild.

5a Remesh / Retopo  Remesh copies ORG_<Object> with a Decimate modifier; Retopo takes a new empty mesh or
                    a picked object. Either gets the two materials LL_<name> (BAo_ mixed with the painted
                    BAp_ by BAp_'s alpha) and MAT_<name> (ALB_ + NOR_), on the uv_normal UV map, and
                    BAo_ is baked from the scan at the set resolution.
5b Paint            the photo to paint from (big thumbnail), Favorites and All Photos in the floating
                    photo panel (Shift+Q, photo_panel.py); Brush (Texture
                    Paint, the photo as a stencil on the camera frame), Fill / Erase (the photo where its
                    camera sees the object) into BAp_, always BAo_'s size.
Edit ALB_           Lasso, Fill, Patch, Move, Liquify in the Image Editor, saved over ALB_ (alb_editor.py).
5c Bake & Export    ALB_ / NOR_ each Bake (01.Bake) or Load (02.Overrides), the finished ALB_ over BAo_ or
                    into 02.Overrides (asked), Lock & Export FBX.
"""
from . import alb_editor, auto_seams, operators, photo_panel, poly_cut, props, uv_tools, uv_tube


def register():
    props.register()
    operators.register()
    alb_editor.register()
    photo_panel.register()
    uv_tools.register()
    uv_tube.register()
    poly_cut.register()
    auto_seams.register()


def unregister():
    auto_seams.unregister()
    poly_cut.unregister()
    uv_tube.unregister()
    uv_tools.unregister()
    photo_panel.unregister()
    alb_editor.unregister()
    operators.unregister()
    props.unregister()
    from . import thumbs
    thumbs.clear()
