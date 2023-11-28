from functools import cached_property

from .base import Connector
from .adapter import Adapter

class Broker:
    '''Connection broker, factory factory.'''
    
    cache: dict[str, Connector]
    
    def __init__(self):
        self.cache = {}
    
    async def connect(self, endpoint):
        conn = self.cache.get(endpoint)
        if conn is None:
            conn = Connector.registry[endpoint]()
            await conn.init()
            self.cache[endpoint] = conn
        return Adapter(conn)