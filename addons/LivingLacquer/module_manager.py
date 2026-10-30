import json
import os
import importlib

_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "modules_config.json")
_LOADED = {}

# Edit entries here via blender-addon-modules — panels.py reads this list
ALL_MODULES = [
    {"name": "project", "op": "livinglacquer.toggle_project", "icon": "FILE_FOLDER"},
    {"name": "linker", "op": "livinglacquer.toggle_linker", "icon": "LINKED"},
    {"name": "scene", "op": "livinglacquer.toggle_scene", "icon": "SCENE_DATA"},
    {"name": "ingest", "op": "livinglacquer.toggle_ingest", "icon": "IMPORT"},
    {"name": "engines", "op": "livinglacquer.toggle_engines", "icon": "MOD_REMESH"},
    {"name": "metashape", "op": "livinglacquer.toggle_metashape", "icon": "OUTLINER_OB_CAMERA"},
    {"name": "rebuild", "op": "livinglacquer.toggle_rebuild", "icon": "MOD_DECIM"},
]


def is_loaded(name):
    return _LOADED.get(name, False)


def _read_config():
    if os.path.exists(_CONFIG_PATH):
        try:
            with open(_CONFIG_PATH) as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _write_config(config):
    try:
        with open(_CONFIG_PATH, "w") as f:
            json.dump(config, f, indent=2)
    except Exception:
        pass


def _get_module(name):
    try:
        return importlib.import_module(f".modules.{name}", package=__package__)
    except ImportError:
        return None


def load_all():
    config = _read_config()
    for entry in ALL_MODULES:
        name = entry["name"]
        mod = _get_module(name)
        if mod and config.get(name, True):
            mod.register()
            _LOADED[name] = True
        else:
            _LOADED[name] = False


def unload_all():
    for entry in reversed(ALL_MODULES):
        name = entry["name"]
        if _LOADED.get(name, False):
            try:
                _get_module(name).unregister()
            except Exception:
                pass
        _LOADED[name] = False


def toggle(name):
    mod = _get_module(name)
    if not mod:
        return
    if _LOADED.get(name, False):
        try:
            mod.unregister()
        except Exception:
            pass
        _LOADED[name] = False
    else:
        mod.register()
        _LOADED[name] = True
    config = _read_config()
    config[name] = _LOADED[name]
    _write_config(config)
