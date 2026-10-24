bl_info = {
    "name": "LivingLacquer",
    "version": (0, 0, 1),
    "blender": (4, 2, 0),
    "location": "View3D > Sidebar > LivingLacquer  |  File > Import > Agisoft Metashape Cameras (.xml)",
    "category": "3D View",
    "description": "Modeling and texturing assistant for scanned lacquerware: photogrammetry cameras, projection and cleanup tools",
    "author": "",
    "doc_url": "",
    "tracker_url": "",
}


def register():
    from . import properties, infos, panels
    properties.register()
    infos.register()
    panels.register()

    from . import module_manager
    module_manager.load_all()


def unregister():
    from . import module_manager
    module_manager.unload_all()

    from . import properties, infos, panels
    panels.unregister()
    infos.unregister()
    properties.unregister()
