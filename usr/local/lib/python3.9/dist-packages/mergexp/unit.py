"""
    Units
"""

# information storage: base unit = byte
# binary prefix, 2**X, e.g. Gigibyte
def kb(value):
    return value * (2**10)

def mb(value):
    return value * (2**20)

def gb(value):
    return value * (2**30)

def tb(value):
    return value * (2**40)

def pb(value):
    return value * (2**50)

def eb(value):
    return value * (2**60)

# time: THE BASE UNIT IS NANOSECONDS !!!!!!
# time: THE BASE UNIT IS NANOSECONDS !!!!!!
# time: THE BASE UNIT IS NANOSECONDS !!!!!!

def s(value):
    return int(value * 1e9)

def ms(value):
    return int(value * 1e6)

def us(value):
    return int(value * 1e3)

def ns(value):
    return value

# network capacity: base unit = bits per second

def bps(value):
    return int(value)

def kbps(value):
    return int(value * 1e3)

def mbps(value):
    return int(value * 1e6)

def gbps(value):
    return int(value * 1e9)

def tbps(value):
    return int(value * 1e12)

def pbps(value):
    return int(value * 1e15)

def ebps(value):
    return int(value * 1e18)

# rate: base unit = Hertz

def hz(value):
    return value

def khz(value):
    return value * 1e3

def mhz(value):
    return value * 1e6

def ghz(value):
    return value * 1e9

def thz(value):
    return value * 1e12
