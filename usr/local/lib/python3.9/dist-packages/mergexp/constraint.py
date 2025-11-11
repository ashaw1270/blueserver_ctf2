from abc import abstractmethod
from .pb import (
    Uint64Constraint,
    Uint32Constraint,
    StringConstraint,
    BoolConstraint,
    FloatConstraint,
    NICModelConstraint,
    GE,
    EQ,
    NE,
    Addressing as PAddressing,
    Routing as PRouting,
    Link as PLink,
    NICModel as PNICModel,
    Emulation as PEmulation,
)

class U64ConstraintObj:
    def __init__(self, constraint=None):
        self.constraint = constraint

    def __eq__(self, value):
        return type(self)(
            constraint = Uint64Constraint(op = EQ, value = value)
        )

    def __ge__(self, value):
        return type(self)(
            constraint = Uint64Constraint(op = GE, value = value)
        )

    @abstractmethod
    def apply(self, target):
        pass

class StringConstraintObj:
    def __init__(self, constraint=None):
        self.constraint = constraint

    def __eq__(self, value):
        return type(self)(
            constraint = StringConstraint(op = EQ, value = value)
        )

    def __ge__(self, value):
        return type(self)(
            constraint = StringConstraint(op = GE, value = value)
        )

    @abstractmethod
    def apply(self, target):
        pass

class FloatConstraintObj:
    def __init__(self, constraint=None):
        self.constraint = constraint

    def __eq__(self, value):
        return type(self)(
            constraint = FloatConstraint(op = EQ, value = value)
        )

    def __ge__(self, value):
        return type(self)(
            constraint = FloatConstraint(op = GE, value = value)
        )

    @abstractmethod
    def apply(self, target):
        pass


class BoolConstraintObj:
    def __init__(self, constraint=None):
        self.constraint = constraint

    def __eq__(self, value):
        return type(self)(
            constraint = BoolConstraint(op = EQ, value = value)
        )

    def __ne__(self, value):
        return type(self)(
            constraint = BoolConstraint(op = NE, value = value)
        )

    @abstractmethod
    def apply(self, target):
        pass


class NICModelConstraintObj:
    '''Base helper class for PortModel, provides __eq__ consructor'''
    def __init__(self, constraint=None):
        self.constraint = constraint

    def __eq__(self, value):
        'Constructs and returns a NICModelConstraint object'
        return type(self)(
            constraint = NICModelConstraint(op = EQ, value = value)
        )

    @abstractmethod
    def apply(self, target):
        pass


class MemoryCapacity(U64ConstraintObj):
    def apply(self, target):
        target.spec.memory.capacity.op = self.constraint.op
        target.spec.memory.capacity.value = self.constraint.value

class ProcCores(U64ConstraintObj):
    def apply(self, target):
        target.spec.proc.cores.op = self.constraint.op
        target.spec.proc.cores.value = self.constraint.value

class DiskCapacity(U64ConstraintObj):
    def apply(self, target):
        target.spec.disks.capacity.op = self.constraint.op
        target.spec.disks.capacity.value = self.constraint.value

class Metal(U64ConstraintObj):
    def apply(self, target):
        target.spec.metal.op = self.constraint.op
        target.spec.metal.value = self.constraint.value

class Image(StringConstraintObj):
    def apply(self, target):
        target.spec.image.op = self.constraint.op
        target.spec.image.value = self.constraint.value

class Host(StringConstraintObj):
    def apply(self, target):
        target.spec.host.op = self.constraint.op
        target.spec.host.value = self.constraint.value

class LinkCapacity(U64ConstraintObj):
    def apply(self, target):
        target.spec.capacity.op = self.constraint.op
        target.spec.capacity.value = self.constraint.value

class LinkLatency(U64ConstraintObj):
    def apply(self, target):
        target.spec.latency.op = self.constraint.op
        target.spec.latency.value = self.constraint.value

class LinkLoss(FloatConstraintObj):
    def apply(self, target):
        target.spec.loss.op = self.constraint.op
        target.spec.loss.value = self.constraint.value

class LinkKindConstraint(U64ConstraintObj):
    def apply(self, target):
        target.spec.kind.op = self.constraint.op
        target.spec.kind.value = self.constraint.value

class ResourcePlatform(StringConstraintObj):
    def apply(self, target):
        target.spec.platform.op = self.constraint.op
        target.spec.platform.value = self.constraint.value

class NetworkLayerConstraint(U64ConstraintObj):
    def apply(self, target):
        target.spec.layer.op = self.constraint.op
        target.spec.layer.value = self.constraint.value

class AddressingConstraint(U64ConstraintObj):
    def apply(self, target):
        target.parameters.addressing.op = self.constraint.op
        target.parameters.addressing.value = self.constraint.value

class RoutingConstraint(U64ConstraintObj):
    def apply(self, target):
        target.parameters.routing.op = self.constraint.op
        target.parameters.routing.value = self.constraint.value

class EmulationConstraint(U64ConstraintObj):
    def apply(self, target):
        target.parameters.emulation.op = self.constraint.op
        target.parameters.emulation.value = self.constraint.value

class ResolutionConstraint(BoolConstraintObj):
    def apply(self, target):
        if self.constraint.op == EQ:
            target.parameters.experimentnetresolution = self.constraint.value
        elif self.constraint.op == NE:
            target.parameters.experimentnetresolution = not self.constraint.value
        else:
            raise Exception("experimentnetresolution only accepts '==' or '!=' constraints")

###
# PortModel, PortCapacity, and PortQueues are applied to a socket element
class PortModel(NICModelConstraintObj):
    '''
    PortModel constraint.  Applies to Socket.
    Example:
        Socket(None, 0, port.model==e1000e)
    '''
    def apply(self, target):
        target.port.model.op = self.constraint.op
        target.port.model.value = self.constraint.value

class PortCapacity(U64ConstraintObj):
    '''
    PortCapacity constraint.  Applies to Socket.
    Example:
        Socket(None, 0, port.capacity==gbps(100))
    '''
    def apply(self, target):
        target.port.capacity.op = self.constraint.op
        target.port.capacity.value = self.constraint.value

class PortQueues(U64ConstraintObj):
    '''
    PortQueues constraint.  Applies to Socket.
    Example:
        Socket(None, 0, port.queues==4)
    '''
    def apply(self, target):
        target.port.queues.op = self.constraint.op
        target.port.queues.value = self.constraint.value

class SriovVF(BoolConstraintObj):
    '''
    Port.SriovVF constraint.  If True, requests that the port uses a VF (Virtual Function).
    Potentially improves network throughput between a VM and VM Host.
    Example:
        Socket(None, 0, port.vf==True)
    '''
    def apply(self, target):
        target.port.SriovVF.op = self.constraint.op
        target.port.SriovVF.value = self.constraint.value


class Memory:
    def __init__(self):
        self.capacity = MemoryCapacity()

class Proc:
    def __init__(self):
        self.cores = ProcCores()

class Disk:
    def __init__(self):
        self.capacity = DiskCapacity()

class Port:
    def __init__(self):
        self.model = PortModel()
        self.capacity = PortCapacity()
        self.queues = PortQueues()
        self.vf = SriovVF()

class LinkProps:
    def __init__(self):
        self.capacity = LinkCapacity()

class LinkKind:
    def __init__(self):
        self.kind = LinkKindConstraint()

memory = Memory()
proc = Proc()
disk = Disk()
link = LinkProps()
metal = Metal()
image = Image()
host = Host()
kind = LinkKindConstraint()
platform = ResourcePlatform()
capacity = LinkCapacity()
latency = LinkLatency()
loss = LinkLoss()
layer = NetworkLayerConstraint()
addressing = AddressingConstraint()
routing = RoutingConstraint()
experimentnetresolution = ResolutionConstraint()
emulation = EmulationConstraint()

lte_4g = PLink.lte_4g
wifi_ac = PLink.wifi_ac

ipv4 = PAddressing.IPv4Addressing
static = PRouting.StaticRouting

click = PEmulation.Click
netem = PEmulation.Netem

### Port constraint helpers
port = Port()
virtio = PNICModel.Virtio
e1000 = PNICModel.E1000
e1000e = PNICModel.E1000E
