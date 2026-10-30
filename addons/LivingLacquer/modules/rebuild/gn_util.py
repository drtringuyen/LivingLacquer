"""A small Geometry Nodes builder, from MultiCamProject's gn_builder, for uvTube."""


def _iface(ng, name, io, typ, default=None, mn=None, mx=None, parent=None, dims=None,
           single=False):
    kw = {"name": name, "in_out": io, "socket_type": typ}
    if parent is not None:
        kw["parent"] = parent
    s = ng.interface.new_socket(**kw)
    if dims is not None:
        s.dimensions = dims
    if single:                  # a plain value, never a field/grid
        s.structure_type = 'SINGLE'
    if default is not None:
        s.default_value = default
    if mn is not None:
        s.min_value = mn
    if mx is not None:
        s.max_value = mx
    return s


class B:
    def __init__(self, tree):
        self.t = tree

    def n(self, typ, loc=(0, 0), parent=None, **props):
        """`loc` is in frame space when `parent` (a frame) is given."""
        node = self.t.nodes.new(typ)
        for k, v in props.items():
            setattr(node, k, v)
        if parent is not None:
            node.parent = parent
        node.location = loc
        return node

    def frame(self, label, loc):
        return self.n("NodeFrame", loc, label=label, label_size=20, shrink=True)

    def link(self, a, b):
        self.t.links.new(a, b)

    def math(self, op, a, b=None, loc=(0, 0), label=None, parent=None):
        m = self.n("ShaderNodeMath", loc, parent, operation=op)
        if label:
            m.label = label
        for i, v in enumerate((a, b)):
            if v is None:
                continue
            if isinstance(v, (int, float)):
                m.inputs[i].default_value = v
            else:
                self.link(v, m.inputs[i])
        return m.outputs[0]

    def vmath(self, op, a, b=None, loc=(0, 0), parent=None):
        m = self.n("ShaderNodeVectorMath", loc, parent, operation=op)
        for i, v in enumerate((a, b)):
            if v is None:
                continue
            self.link(v, m.inputs[i])
        return m

    def reroute(self, src, loc):
        r = self.n("NodeReroute", loc)
        self.link(src, r.inputs[0])
        return r.outputs[0]
