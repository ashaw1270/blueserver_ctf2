from uuid import uuid4
from functools import reduce
import base64
import google.protobuf.json_format
from .pb import (
    Node as PNode,
    Link as PLink,
    Socket as PSocket,
    Endpoint as PEndpoint,
    Network as PNetwork,
    PortSpec as PPortSpec,
    ExperimentParameters as PExpParam,
    Protocol as Proto,
)
from .constraint import port as PORT
from .exceptions import MissingNodeErr

class Network():
    def __init__(self, name, *args):
        self.id = name
        self.nodes = []
        self.links = []
        self.parameters = PExpParam()

        # default is to resolve experiment names
        # before infra names.
        self.parameters.experimentnetresolution = True

        for constraint in args:
            constraint.apply(self)

    def node(self, name, *args):
        n = Node(name, *args)
        self.nodes.append(n)
        return n

    def connect(self, nodes, *args):
        for n in nodes:
            if n not in self.nodes:
                raise MissingNodeErr(n.spec.id)
        sockets = [x.socket() for x in nodes]
        return self.connect_sockets(sockets, *args)

    def connect_sockets(self, sockets, *args):
        l = Link(sockets, *args)
        self.links.append(l)
        return l

    def xir(self):
        n = PNetwork(id=self.id, parameters=self.parameters)
        for x in self.nodes:
            n.nodes.append(x.xir())
        for x in self.links:
            n.links.append(x.xir())
        return n

    def save_xir(self):
        buf = base64.b64encode(self.xir().SerializeToString()).decode()
        out = open('%s.pb64'%self.id, 'w')
        out.write(buf)
        out.close()

    def save_json(self):
        buf = google.protobuf.json_format.MessageToJson(self.xir())
        out = open('%s.json'%self.id, 'w')
        out.write(buf)
        out.close()

    def useSRIOV(self, val: bool = True):
        if val:
            # by default VF use is disabled
            Socket.default_constraints.append(PORT.vf==True)

class Socket():
    # default_constraints are applied before user-passed
    default_constraints = []

    def __init__(self, parent, index, *args):
        self.parent = parent
        self.index = index
        self.endpoint = None
        self.addrs = []
        self.port = PPortSpec()

        for constraint in Socket.default_constraints:
            constraint.apply(self)

        for constraint in args:
            constraint.apply(self)

    def str(self):
        return "%s.%d"%(self.parent.spec.id, self.index)


class Endpoint:
    def __init__(self, parent, index):
        self.parent = parent
        self.index = index
        self.socket = None

class Node():
    def __init__(self, name, *args):
        self.spec = PNode(id=name)
        self.properties = {}
        self.sockets = []
        for constraint in args:
            constraint.apply(self)
        self.properties['ingress'] = []

    def color(self, c):
        self.spec.viz.color = c

    def size(self, c):
        self.spec.viz.size = c

    def socket(self, *args):
        '''
        Create a new socket for this node with optional given constraints.
        Example:
            node = Node(...)
            sock = node.socket(SriovVF()==True, PortCapacity()==gbps(1))
        '''
        s = Socket(self, len(self.sockets), *args)
        self.sockets.append(s)
        return s

    def ingress(self, proto, port):
        # Not sure how else to test for valid proto other than to
        # enumerate them. May be a grpc util for this.
        valid = [Proto.Name(Proto.http),
                 Proto.Name(Proto.https),
                 Proto.Name(Proto.tcp),
                 Proto.Name(Proto.udp),
        ]
        if proto not in valid:
            raise Exception("Unsupported protocol in node ingress: " + proto + ". Supported protocols " + ", ".join(valid))

        # ingress properties format is list of proto:port strings.
        self.properties['ingress'].append(str(proto) + ":" + str(port))

    def xir(self):
        del self.spec.sockets[:]
        for s in self.sockets:
            ps = PSocket(index=s.index, port=s.port)
            if s.endpoint:
                ps.endpoint.element = s.endpoint.parent.spec.id
                ps.endpoint.index = s.endpoint.index
                for a in s.addrs:
                    ps.addrs.append(a)

            self.spec.sockets.append(ps)

        # assumes properties values are lists. TODO: check and bomb if not.
        self.spec.properties.keyvalues.clear()
        for k, vs in self.properties.items():
            for v in vs:
                self.spec.properties.keyvalues[k].values.append(v)

        return self.spec

class Link():
    def __init__(self, sockets, *args):
        self.endpoints = []
        self.properties = {}
        self.spec = PLink()
        self.spec.id = str(
            reduce(lambda x,y: x + "~" + y, map(lambda x: x.str(), sockets))
        )
        for _ in sockets:
            self.endpoints.append(
                Endpoint(parent=self, index=len(self.endpoints))
            )

        for (s,e) in zip(sockets, self.endpoints):
            s.endpoint = e
            e.socket = s

        for constraint in args:
            constraint.apply(self)

    # TODO: our model assumes that nodes are only connected to the same network
    # once.
    def __getitem__(self, x):
        for e in self.endpoints:
            if e.socket.parent.spec.id == x.spec.id:
                return e
        raise IndexError()

    def xir(self):
        x = self.spec
        del self.spec.endpoints[:]
        for e in self.endpoints:
            pe = PEndpoint(index=e.index)
            if e.socket:
                pe.socket.element = e.socket.parent.spec.id
                pe.socket.index = e.socket.index
            x.endpoints.append(pe)

        # assumes properties values are lists. TODO: check and bomb if not.
        self.spec.properties.keyvalues.clear()
        for k, vs in self.properties.items():
            for v in vs:
                x.properties.keyvalues[k].values.append(v)

        return x

__xp = {}
def experiment(topo):
    global __xp
    __xp['topo'] = topo
