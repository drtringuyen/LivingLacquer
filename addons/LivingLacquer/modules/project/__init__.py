"""Project: step 1 of the scan pipeline and the Scan Pipeline panel.

New Object picks the next free NN in the objects folder, creates NN.<Object>\\ with the scan
folders (docs/PLAN_scan_pipeline.md §2) and livinglacquer.json, and saves the current file as
NN.<Object>.blend. Open Object opens the .blend of an object folder. Steps 2-8 stay greyed out
until the file is saved inside an object folder.
"""
from . import jobs, operators, prefs, state, steps, ui, viewbar


def register():
    prefs.register()
    state.register()
    jobs.register()
    steps.register()
    operators.register()
    viewbar.register()
    ui.register()


def unregister():
    ui.unregister()
    viewbar.unregister()
    operators.unregister()
    steps.unregister()
    jobs.unregister()
    state.unregister()
    prefs.unregister()
