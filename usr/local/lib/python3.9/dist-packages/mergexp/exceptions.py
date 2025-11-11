class MissingNodeErr(Exception):
    def __init__(self, name):
        super().__init__(f"Cannot connect node {name} as it not in the network. Use net.node() instead of Node() to create a network node.")
