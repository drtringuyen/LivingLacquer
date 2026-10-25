"""Linker: step 5 of the scan pipeline, Check Links.

Check reads the object folder (folder names, photos, camera XML, model, textures, marker) and
every file path in the .blend, and lists what is fine, what needs a look and what is broken,
with the plan's codes (docs/PLAN_scan_pipeline.md §6). Fix… renames old folders, relinks
missing files it finds in the object folder, copies external files in, makes paths relative
and writes livinglacquer.json. Save the .blend afterwards.
"""
from . import operators


def register():
    operators.register()


def unregister():
    operators.unregister()
