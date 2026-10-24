"""The add-on's 3D Viewport sidebar tab: rename it, move it up / down among the add-on
tabs, share it with other add-ons. A drop-in module: the same file in every add-on.

Use it:
    __init__.register():   sidebar_tab.register()   (after the panels and modules)
    __init__.unregister(): sidebar_tab.unregister() (before them)
    each panel register(): sidebar_tab.register_panel(cls)  instead of register_class
    the Infos panel:       draw_header -> sidebar_tab.draw_header(self.layout, "Infos")
                           in draw     -> sidebar_tab.draw(layout)   (the Tab name row)

Shared state: <Blender config>/sidebar_tabs.json, read and written by every add-on that
has this module, so their moves never fight over the order:
    {"order": ["TabA", "TabB", ...], "names": {"<add-on module>": "<tab name>"}}
It survives add-on reloads and needs no preferences save. SIDEBAR_TABS_FILE (environment)
points it somewhere else, e.g. for tests.

Tab name: panels take tab_name() as their bl_category when they register. Renaming
registers this add-on's panels again under the new name; the sidebar stays on it. Two
add-ons with the same tab name share one tab, which moves as one entry.

Order: Blender shows sidebar tabs in panel registration order and has no API to read or
set it. Its own tabs (Item, Tool, View... from bl_ui) always come first. A move registers
every add-on panel of the 3D Viewport sidebar again, tab by tab, in the saved order; the
first add-on to start applies the saved order once for all of them.

Caveat: a panel registered again loses its open / closed state and dragged order. Other
add-ons' preferences, settings and data are never touched, only their Panel classes.
"""
import json
import os
import sys

import bpy

ADDON = __package__                              # the add-on's module name
ID = ADDON.rsplit(".", 1)[-1].lower()            # operator / property prefix
PROP = ID + "_tab_name"                          # WindowManager property behind the field
_APPLIED = "sidebar_tabs_applied"                # driver_namespace key: order applied once


# ------------------------------------------------------------ shared file

def _path():
    return os.environ.get("SIDEBAR_TABS_FILE") or os.path.join(
        bpy.utils.user_resource('CONFIG'), "sidebar_tabs.json")


def _load():
    try:
        with open(_path(), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        data = {}
    data.setdefault("order", [])
    data.setdefault("names", {})
    return data


def _store(data):
    path = _path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path + ".tmp", "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1)
    os.replace(path + ".tmp", path)


def _unique(tabs):
    """Each tab once, at its first place (add-ons sharing a tab are one entry)."""
    seen = set()
    return [t for t in tabs if t and not (t in seen or seen.add(t))]


# ------------------------------------------------------------ tab name

def default_name():
    info = getattr(sys.modules.get(ADDON), "bl_info", None) or {}
    return info.get("name") or ADDON.rsplit(".", 1)[-1]


def tab_name():
    """The sidebar tab this add-on's panels show in."""
    return (_load()["names"].get(ADDON) or "").strip() or default_name()


def set_tab_name(value):
    old = tab_name()
    data = _load()
    value = (value or "").strip()
    if value and value != default_name():
        data["names"][ADDON] = value
    else:
        data["names"].pop(ADDON, None)
    _store(data)
    _apply_name(old)


def register_panel(cls):
    """Register a panel of this add-on in its named tab."""
    cls.bl_category = tab_name()
    bpy.utils.register_class(cls)


def _our_panels():
    return [c for c in _sidebar_panels(builtin=False)
            if c.__module__ == ADDON or c.__module__.startswith(ADDON + ".")]


def _apply_name(old):
    """Move this add-on's registered panels to tab_name(). A panel's category is read at
    registration, so they are registered again: sub-panels out first, in last."""
    name = tab_name()
    panels = _our_panels()
    if all(c.bl_category == name for c in panels):
        return
    # a sidebar showing the old tab follows it to the new name instead of jumping away
    active = [(r, name if cat == old else cat) for r, cat in _active_tabs()]
    parents = [c for c in panels if not getattr(c, "bl_parent_id", "")]
    children = [c for c in panels if getattr(c, "bl_parent_id", "")]
    for c in children + parents:
        bpy.utils.unregister_class(c)
    for c in parents + children:
        c.bl_category = name
        bpy.utils.register_class(c)
    _renamed(old, name)                  # registering again moved it to the bottom
    restore_active_tabs(active)


# ------------------------------------------------------------ order

def _subclasses(cls):
    out = []
    for c in cls.__subclasses__():
        out.append(c)
        out.extend(_subclasses(c))
    return out


def _sidebar_panels(builtin):
    """Registered panels of the 3D Viewport sidebar, Blender's own or add-on ones."""
    seen, out = set(), []
    for c in _subclasses(bpy.types.Panel):
        if c in seen or not getattr(c, "is_registered", False):
            continue
        seen.add(c)
        if (getattr(c, "bl_space_type", "") == 'VIEW_3D' and getattr(c, "bl_region_type", "") == 'UI'
                and (c.__module__.split(".")[0] == "bl_ui") == builtin):
            out.append(c)
    return out


def _builtin_tabs():
    """Tabs Blender itself fills: they stay first whatever add-on panels join them."""
    return {getattr(c, "bl_category", "") for c in _sidebar_panels(builtin=True)}


def _by_idname(panels):
    return {getattr(c, "bl_idname", c.__name__): c for c in panels}


def _depth(c, ids):
    d, p = 0, getattr(c, "bl_parent_id", "")
    while p in ids and d < 16:
        d += 1
        p = getattr(ids[p], "bl_parent_id", "")
    return d


def _category(c, ids):
    root = c
    for _ in range(16):
        p = getattr(root, "bl_parent_id", "")
        if p not in ids:
            break
        root = ids[p]
    return getattr(root, "bl_category", "") or "Misc"


def _addon_rank(c):
    """Guess for tabs with no saved place: the order the add-ons were enabled in."""
    mods = [a.module for a in bpy.context.preferences.addons]
    for i, m in enumerate(mods):
        if c.__module__ == m or c.__module__.startswith(m + "."):
            return i
    return len(mods)


def current_order():
    """The add-on tabs, top to bottom: the saved order first, then any new tab where its
    add-on was enabled."""
    panels = _sidebar_panels(builtin=False)
    ids = _by_idname(panels)
    builtin = _builtin_tabs()
    first = {}
    for i, c in enumerate(panels):
        cat = _category(c, ids)
        if cat not in first and cat not in builtin:
            first[cat] = (_addon_rank(c), i)
    saved = [t for t in _unique(_load()["order"]) if t in first]
    rest = sorted((t for t in first if t not in saved), key=first.get)
    return saved + rest


def _save_order(order):
    data = _load()
    data["order"] = _unique(order)
    _store(data)


def apply_order(order):
    """Register every add-on sidebar panel again, tab by tab, in this order. Returns the
    panels that failed to register again."""
    panels = _sidebar_panels(builtin=False)
    ids = _by_idname(panels)
    rank = {t: i for i, t in enumerate(order)}
    rank.update((t, -1) for t in _builtin_tabs())       # their place is fixed anyway
    pos = {c: i for i, c in enumerate(panels)}
    ordered = sorted(panels, key=lambda c: (rank.get(_category(c, ids), len(rank)),
                                            _depth(c, ids), pos[c]))
    active = _active_tabs()
    for c in sorted(panels, key=lambda c: -_depth(c, ids)):       # sub-panels out first
        try:
            bpy.utils.unregister_class(c)
        except RuntimeError:
            pass
    failed = []
    for c in ordered:
        try:
            bpy.utils.register_class(c)
        except (RuntimeError, ValueError) as e:
            failed.append("%s: %s" % (c.__name__, e))
    bpy.app.driver_namespace[_APPLIED] = _applied_key(order)
    restore_active_tabs(active)
    return failed


def _applied_key(order):
    return "|".join(order) + "#" + ",".join(sorted(_by_idname(_sidebar_panels(builtin=False))))


def apply_saved():
    """The saved order, once for all add-ons that have this module (startup, reload)."""
    if _load()["order"]:
        order = current_order()
        if bpy.app.driver_namespace.get(_APPLIED) != _applied_key(order):
            apply_order(order)
    return None


def move(step):
    """Move this add-on's tab step places (-1 up, +1 down). Returns (moved, failed)."""
    order = current_order()
    ours = tab_name()
    if ours not in order:
        return False, []
    i = order.index(ours)
    j = max(0, min(len(order) - 1, i + step))
    if i == j:
        return False, []
    order.insert(j, order.pop(i))
    _save_order(order)
    return True, apply_order(order)


def _renamed(old, new):
    """Keep the saved place of a renamed tab. Renamed into a tab that already exists, it
    joins that tab at its place. Leaving a tab other add-ons still show in, that tab keeps
    its place and the new one comes right after it."""
    saved = _unique(_load()["order"])
    if old in saved and old != new:
        panels = _sidebar_panels(builtin=False)
        ids = _by_idname(panels)
        shared = any(_category(c, ids) == old for c in panels)
        if new in saved:
            if not shared:
                saved.remove(old)
        elif shared:
            saved.insert(saved.index(old) + 1, new)
        else:
            saved[saved.index(old)] = new
        _save_order(saved)
    if saved:
        apply_order(current_order())


# ------------------------------------------------------------ active tab

def _sidebars():
    wm = bpy.context.window_manager
    for w in wm.windows if wm else ():
        for a in w.screen.areas:
            if a.type == 'VIEW_3D':
                for r in a.regions:
                    if r.type == 'UI':
                        yield a, r


def _active_tabs():
    """Registering panels again switches a sidebar to another tab: remember each one's."""
    return [(r, getattr(r, "active_panel_category", "")) for _a, r in _sidebars()]


def _set_active_tabs(active):
    """True when every sidebar shows the tab it should."""
    done = True
    for r, cat in active:
        try:
            if cat and r.active_panel_category != cat:
                r.active_panel_category = cat
                done = done and r.active_panel_category == cat
        except TypeError:
            done = False                    # a new tab the sidebar has not drawn yet
        except (AttributeError, ReferenceError):
            pass                            # read-only before Blender 4.x, or region gone
    for a, _r in _sidebars():
        a.tag_redraw()
    return done


def _draw_sidebars():
    """Draw the windows with a sidebar now, so a new tab is known to them (they may not
    redraw on their own while Blender is not the focused window)."""
    wm = bpy.context.window_manager
    for w in wm.windows if wm else ():
        if any(a.type == 'VIEW_3D' for a in w.screen.areas):
            try:
                with bpy.context.temp_override(window=w):
                    bpy.ops.wm.redraw_timer(type='DRAW_WIN', iterations=1)
            except (RuntimeError, TypeError):
                pass


def restore_active_tabs(active):
    """Show the remembered tabs again. A tab that was just created only exists in the
    sidebar after it redraws, so a miss is retried after a forced redraw."""
    if _set_active_tabs(active):
        return
    tries = [10]

    def retry():
        tries[0] -= 1
        _draw_sidebars()
        return None if _set_active_tabs(active) or not tries[0] else 0.1

    bpy.app.timers.register(retry, first_interval=0.01)


# ------------------------------------------------------------ UI

def draw(layout):
    """The Tab name row: label, name field, reset, up / down."""
    split = layout.split(factor=0.3)
    split.label(text="Tab name:")
    row = split.row(align=True)
    row.prop(bpy.context.window_manager, PROP, text="", icon='WINDOW')
    reset = row.row(align=True)
    reset.enabled = tab_name() != default_name()
    reset.operator(ID + ".reset_tab_name", text="", icon='LOOP_BACK')
    row.operator(ID + ".move_tab", text="", icon='TRIA_UP').direction = 'UP'
    row.operator(ID + ".move_tab", text="", icon='TRIA_DOWN').direction = 'DOWN'


def draw_header(layout, title):
    """A panel header with the add-on name greyed in brackets, to tell it apart in a tab
    shared with other add-ons (the panel's bl_label is "")."""
    row = layout.row(align=True)
    row.label(text=title)
    sub = row.row(align=True)
    sub.active = False
    sub.label(text="(%s)" % default_name())


def _move_execute(self, context):
    moved, failed = move(-1 if self.direction == 'UP' else 1)
    for f in failed:
        self.report({'WARNING'}, "Could not register again: " + f)
    if not moved:
        self.report({'INFO'}, "The tab is already at the %s" % ("top" if self.direction == 'UP' else "bottom"))
    return {'FINISHED'}


MoveTab = type(ID.upper() + "_OT_move_tab", (bpy.types.Operator,), {
    "bl_idname": ID + ".move_tab",
    "bl_label": "Move Tab",
    "bl_description": ("Move this add-on's sidebar tab up or down among the add-on tabs "
                       "(Blender's own tabs stay first). Registers the sidebar panels of "
                       "every add-on again, so their open / closed state may reset"),
    "__annotations__": {"direction": bpy.props.EnumProperty(
        items=(('UP', "Up", ""), ('DOWN', "Down", "")))},
    "execute": _move_execute,
})


ResetTabName = type(ID.upper() + "_OT_reset_tab_name", (bpy.types.Operator,), {
    "bl_idname": ID + ".reset_tab_name",
    "bl_label": "Reset Tab Name",
    "bl_description": "Show this add-on in its own tab again (the add-on name)",
    "execute": lambda self, context: set_tab_name("") or {'FINISHED'},
})


def _startup():
    apply_saved()
    return None


def register():
    bpy.utils.register_class(MoveTab)
    bpy.utils.register_class(ResetTabName)
    setattr(bpy.types.WindowManager, PROP, bpy.props.StringProperty(
        name="Tab name",
        description=("Sidebar tab this add-on shows in. Empty: %s. The same name as another "
                     "add-on's tab merges them. Kept in sidebar_tabs.json" % default_name()),
        get=lambda self: tab_name(),
        set=lambda self, value: set_tab_name(value)))
    # this add-on's panels just registered (at the bottom): the saved order is due again,
    # once every add-on has registered, and only once for all of them
    bpy.app.driver_namespace.pop(_APPLIED, None)
    bpy.app.timers.register(_startup, first_interval=0.1)


def unregister():
    if bpy.app.timers.is_registered(_startup):
        bpy.app.timers.unregister(_startup)
    if hasattr(bpy.types.WindowManager, PROP):
        delattr(bpy.types.WindowManager, PROP)
    bpy.utils.unregister_class(ResetTabName)
    bpy.utils.unregister_class(MoveTab)
