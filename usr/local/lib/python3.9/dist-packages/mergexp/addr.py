import ipaddress

def ip4(*args):
    addrs = []
    for x in args:
        ip = ipaddress.IPv4Interface(x)
        addrs.append(x)
    return addrs

