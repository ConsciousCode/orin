from contextlib import contextmanager
import json
import time
from typing import Iterable, Iterator, Literal, Optional
import sqlite3

from util import read_file

from .connector import AssistantId
from .typing import json_value, dataclass, dataclasses

VERSION = 0
'''Version counter for database consistency.'''

SCHEMA = read_file("schema.sql")

type Role = Literal['user', 'assistant', 'system']
'''Message role.'''

@dataclass
class Row:
    def __iter__(self):
        return iter(dataclasses.astuple(self))

@dataclass
class ArchetypeRow(Row):
    type primary_key = int
    rowid: primary_key
    
    api_id: AssistantId
    created_at: int
    deleted_at: Optional[int]
    name: str
    model: str
    description: str
    instructions: str

@dataclass
class AgentRow(Row):
    type primary_key = int
    rowid: primary_key
    
    type: str
    created_at: int
    deleted_at: Optional[int]
    ring: int
    name: str
    description: str
    config: str

@dataclass
class SubscriptionRow(Row):
    channel: str
    agent_id: AgentRow.primary_key

@dataclass
class MessageRow(Row):
    type primary_key = int
    rowid: primary_key
    
    role: Role
    agent_id: AgentRow.primary_key
    content: str
    created_at: int

@dataclass
class PushRow(Row):
    channel: str
    agent_id: AgentRow.primary_key
    message_id: MessageRow.primary_key

class Database:
    '''Holds logic for database persistence.'''
    
    sql: sqlite3.Connection
    '''Connection to the database.'''
    
    def __init__(self, sql: sqlite3.Connection):
        self.sql = sql
        self.sql.row_factory = sqlite3.Row
        self.sql.executescript(SCHEMA)
    
    @contextmanager
    def transaction(self):
        '''Wrap a logical transaction to commit any pending transactions.'''
        
        try:
            cursor = self.sql.cursor()
            yield cursor
            self.sql.commit()
        except BaseException as e:
            self.sql.rollback()
            raise
        finally:
            cursor.close()
    
    def cast_execute(self, schema: type, query: str, values: tuple=()):
        cursor = self.sql.cursor()
        cursor.row_factory = lambda conn, row: schema(*row)
        return cursor.execute(query, values)
    
    def create_archetype(self,
        name: str,
        description: str,
        model: str,
        config: json_value
    ) -> ArchetypeRow.primary_key:
        with self.transaction() as cursor:
            return cursor.execute('''
                INSERT INTO archetype (name, description, model, config)
                    VALUES (?, ?, ?, ?)
            ''', (name, description, model, json.dumps(config))
            ).lastrowid or 0
    
    def create_agent(self,
        type: str, ring: int, name: str,
        description: str, config: json_value
    ) -> AgentRow.primary_key:
        with self.transaction() as cursor:
            return cursor.execute('''
                INSERT INTO agent
                    (created_at, type, ring, name,
                    description, config) VALUES (?, ?, ?, ?, ?, ?)
                ''', (
                    int(time.time()), type , ring, name,
                    description, json.dumps(config)
                )
            ).lastrowid or 0
    
    def destroy_agent(self, agent: AgentRow.primary_key):
        with self.transaction() as cursor:
            cursor.execute('''
                UPDATE agent SET deleted_at=? WHERE id=?
            ''', (int(time.time()), agent,))
    
    def subscribe(self, chan: str, agent: AgentRow.primary_key):
        with self.transaction() as cursor:
            cursor.execute('''
                INSERT INTO subscription (channel, agent_id) VALUES (?, ?)
            ''', (chan, agent))
    
    def unsubscribe(self, channel: str, agent: AgentRow.primary_key):
        with self.transaction() as cursor:
            cursor.execute('''
                DELETE FROM subscription (channel, agent_id) VALUES (?, ?)
            ''', (channel, agent))
    
    def unsubscribe_all(self, channel: str):
        with self.transaction() as cursor:
            cursor.execute('''
                DELETE FROM subscription WHERE channel=?
            ''', (channel,))
    
    def push(self,
        channel: str,
        agent: AgentRow.primary_key,
        message: MessageRow.primary_key
    ):
        with self.transaction() as cursor:
            cursor.execute('''
                INSERT INTO push (channel, agent_id, message_id) VALUES (?, ?, ?)
            ''', (channel, agent, message))
    
    def push_many(self, rows: Iterable[tuple[str, int, int]]):
        with self.transaction() as cursor:
            cursor.executemany('''
                INSERT INTO push (channel, agent_id, message_id) VALUES (?, ?, ?)
            ''', rows)
    
    def message(self,
        role: Role,
        agent: AgentRow.primary_key,
        content: str,
        created_at: int
    ) -> MessageRow.primary_key:
        with self.transaction() as cursor:
            return cursor.execute('''
                INSERT INTO message
                    (role, agent_id, content, created_at)
                    VALUES (?, ?, ?, ?)
            ''', (role, agent, content, created_at)).lastrowid or 0
    
    def load_archetype_tools(self, archetype: ArchetypeRow.primary_key) -> Iterator[str]:
        return self.cast_execute(str, '''
            SELECT tool FROM archetype_tool WHERE archetype_id=?
        ''', (archetype,))
    
    def load_archetypes(self) -> Iterator[ArchetypeRow]:
        return self.cast_execute(ArchetypeRow,
            "SELECT rowid, * FROM archetype"
        )
    
    def load_agents(self) -> Iterator[AgentRow]:
        return self.cast_execute(AgentRow,
            "SELECT rowid, * FROM agent WHERE deleted_at IS NULL"
        )
    
    def load_subscriptions(self) -> Iterator[SubscriptionRow]:
        return self.cast_execute(SubscriptionRow,
            "SELECT * FROM subscription"
        )