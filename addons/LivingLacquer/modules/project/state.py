"""What the panel needs about the open .blend, cached so drawing never touches the disk
(object folders usually stream from Google Drive)."""
import bpy
from bpy.app.handlers import persistent

from . import marker, paths

_cache = {"blend": None, "root": "", "marker": None}


def get():
    """{'blend', 'root', 'marker'} for the current file; refreshed when the file changes."""
    if _cache["blend"] != bpy.data.filepath:
        refresh()
    return _cache


def refresh():
    blend = bpy.data.filepath
    root = paths.object_root(blend)
    _cache.update(blend=blend, root=root, marker=marker.read(root) if root else None)
    return _cache


@persistent
def _on_file_change(*_args):
    refresh()


def register():
    bpy.app.handlers.load_post.append(_on_file_change)
    bpy.app.handlers.save_post.append(_on_file_change)


def unregister():
    for h in (bpy.app.handlers.load_post, bpy.app.handlers.save_post):
        if _on_file_change in h:
            h.remove(_on_file_change)
