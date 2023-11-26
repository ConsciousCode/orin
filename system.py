import asyncio
import json
import time
import sqlite3
from typing import Any
from prompt_toolkit.patch_stdout import patch_stdout

from typedef import Optional, defaultdict, dataclass, ABC, abstractmethod
from config import DUMB_MODEL, MODEL
from tool import Tool
from util import logger, read_file
from connector import AssistantId, connect, Connection
from db import AgentRow, Database, MessageRow

@dataclass
class Message:
    id: MessageRow.primary_key
    src: 'Agent'
    channel: str
    content: str
    created_at: float
    
    def __str__(self):
        ts = time.strftime("%H:%M:%S", time.localtime(self.created_at))
        channel = json.dumps(self.channel)
        content = json.dumps(self.content)
        
        return f"[{ts}]\t{self.src.qualname()}:\t{channel}\t{content}"

class Agent(ABC):
    '''Abstract agent participating in the consortium.'''
    
    registry: dict[str, type['Agent']] = {}
    
    @classmethod
    def register(cls, agent):
        cls.registry[agent.__name__] = agent
    
    id: AgentRow.primary_key
    '''Id of the agent in the database.'''
    
    name: str
    '''Name of the agent - functions as a short description.'''
    
    description: str
    '''Longer description of the agent for the benefit of other agents.'''
    
    ring: int
    '''Protection ring of the agent.'''
    
    config: Any
    '''Local configuration for the agent.'''
    
    msg: asyncio.Queue[Message]
    '''Pending messages to be processed.'''
    
    def __init__(self,
        id: AgentRow.primary_key,
        name: Optional[str]=None,
        description: Optional[str]=None,
        ring: Optional[int]=None,
        config: Any=None
    ):
        self.id = id
        # Note: Uses agent defaults if available, otherwise AttributeError
        self.name = name or self.name
        self.description = description or self.description
        self.ring = ring or self.ring
        self.config = config
        
        self.msgq = asyncio.Queue()
    
    def idchan(self):
        return f"@{self.id}"
    
    def qualname(self) -> str:
        '''Return the fully qualified name of the agent, including any ids.'''
        return f"{self.name}{self.idchan()}:{self.ring}"
    
    def push(self, msg: Message):
        '''Push a message to the agent.'''
        logger.debug(f"Servitor.push {msg}")
        self.msgq.put_nowait(msg)
    
    async def pull(self):
        '''Pull all pending messages from the message queue.'''
        
        yield await self.msgq.get()
        
        while not self.msgq.empty():
            yield self.msgq.get_nowait()
    
    @abstractmethod
    async def run(self, kernel: 'Kernel'):
        '''Run the agent.'''
    
    async def on_destroy(self, kernel: 'Kernel'):
        '''Callback for when the agent is destroyed. Allows alerting subscribers.'''
        pass

class Kernel:
    '''System architecture object.'''
    
    taskgroup: asyncio.TaskGroup
    '''TaskGroup for all running agents.'''
    
    db: Database
    '''Database connection.'''
    
    openai: Connection
    '''Owned client provided to openai.'''
    
    agents: dict[AgentRow.primary_key, Agent]
    '''Map of locally instantiated agents.'''
    
    subs: defaultdict[str, set[Agent]]
    '''Subscription map.'''
    
    cache: dict[type[Agent], Any]
    '''Cache for agents to use.'''
    
    tools: dict[str, type[Tool]]
    '''Available tools.'''
    
    agent: Agent
    '''Agent representing the kernel.'''
    
    def __init__(self, taskgroup: asyncio.TaskGroup, db: Database, openai: Connection, tools: dict[str, type[Tool]]):
        self.taskgroup = taskgroup
        self.db = db
        self.openai = openai
        self.archetypes = {}
        self.agents = {}
        self.cache = {}
        self.subs = defaultdict(set)
        self.tools = tools
    
    def agent_type(self, name):
        '''Return an agent type given its name.'''
        
        return Agent.registry[name]
    
    async def parse_json(self, doc: str):
        '''Attempt to parse the JSON using an LLM as backup for typos.'''
        
        first = None
        for i in range(3):
            try:
                return json.loads(doc)
            except json.JSONDecodeError as e:
                logger.debug(f"Argument parse {e!r}")
                if first is not None:
                    first = e
                
                doc = str(self.openai.chat(DUMB_MODEL, messages=[
                    {"role": "system", "content": "Respond with all errors in the given JSON document corrected and nothing else."},
                    {"role": "system", "content": str(e)},
                    {"role": "user", "content": doc}
                ]))
        
        assert first is not None
        raise first
    
    def update_config(self, agent, config):
        '''Update the agent's configuration.'''
        
        if config:
            self.db.set_config(agent.id, {**agent.config, **config})
    
    def create_agent(self,
        type: str,
        ring: Optional[int]=None,
        name: Optional[str]=None,
        description: Optional[str]=None,
        config: Any=None
    ):
        '''Create a new agent.'''
        
        logger.info(f"create_agent({type!r}, {ring!r}, {name!r}, {description!r}, {config!r})")
        
        AgentType = self.agent_type(type)
        agent_id = self.db.create_agent(
            type,
            ring or AgentType.ring,
            name or AgentType.name,
            description or AgentType.description,
            config
        )
        agent = AgentType(agent_id, name, description, ring, config)
        self.agents[agent_id] = agent
        self.taskgroup.create_task(agent.run(self))
        return agent
    
    async def destroy(self, id):
        '''Destroy an agent.'''
        
        logger.info(f"destroy({id})")
        
        assert self.db is not None
        
        self.db.destroy_agent(id)
        agent = self.agents.pop(id)
        await agent.on_destroy(self)
        self.unsubscribe_all(agent.idchan())
        
        if agent.name not in self.agents:
            # No other agents have this name, delete it
            self.subs.pop(agent.name, None)
    
    def subscribe(self, agent: Agent, chan: str):
        '''Subscribe an agent to channel.'''
        
        logger.info(f"subscribe({agent.qualname()!r}, {chan!r})")
        
        assert self.db is not None
        self.db.subscribe(chan, agent.id)
        self.subs[chan].add(agent)
    
    def unsubscribe_all(self, chan: str):
        '''Unsubcribe all agents from a channel.'''
        
        logger.info(f"unsubscribe_all({chan!r})")
        
        assert self.db is not None
        self.db.unsubscribe_all(chan)
        self.subs.pop(chan, None)
    
    def unsubscribe(self, agent: Agent, chan: str):
        '''Unsubscribe agent from channel.'''
        
        logger.info(f"unsubscribe({agent.qualname()!r}, {chan!r})")
        
        assert self.db is not None
        self.db.unsubscribe(chan, agent.id)
        
        try:
            if channel := self.subs[chan]:
                channel.remove(agent)
                # Clean up unused channels
                if len(channel) == 0:
                    del self.subs[chan]
            
            return True
        except KeyError:
            return False
    
    def push(self, chan: str, row: MessageRow):
        '''Push a message to a channel. (One db message -> many pushes)'''
        
        msg = Message(
            row.rowid, self.agents[row.agent_id],
            chan, row.content, row.created_at
        )
        
        if chan == "*":
            # Broadcast
            subscribers = self.agents.values()
        else:
            subscribers = self.subs.get(chan)
            if subscribers is None:
                return False
        
        broadcast = self.subs.get("*") or set()
        
        logger.debug("publish(): Push")
        pushes: list[tuple[str, int, int]] = []
        for target in subscribers:
            if target.id in broadcast:
                continue
            
            pushes.append((chan, target.id, msg.id))
            # Do not push to the agent, thread automatically adds it
            if target.id != row.agent_id:
                target.push(msg)
        self.db.push_many(pushes)
        
        logger.debug("publish(): Finish")
        
        return True
    
    def publish(self, agent: Agent, chan: Optional[str], content: str):
        '''
        Publish a message to a channel.
        If channel is unspecified, publish to subscribers of the agent (name and id).
        
        Returns whether or not the channel has subscribers.
        '''
        
        logger.info(f"publish({agent.qualname()!r}, {chan!r}, {content!r})")
        logger.debug("publish(): Creating message")
        
        created_at = int(time.time())
        row = self.db.message("user", agent.id, content, created_at)
        
        # Broadcast subscribers get all messages
        broadcast = self.subs.get("*")
        if broadcast is not None:
            pushes = []
            for target in broadcast:
                pushes.append((chan or "", target.id, row.rowid))
                if target.id != row.agent_id:
                    target.push(Message(row.rowid, agent, chan or "", content, created_at))
            self.db.push_many(pushes)
        
        if chan is None:
            self.push(agent.idchan(), row)
            self.push(agent.name, row)
            return True
        else:
            return self.push(chan, row)
    
    async def load_agents(self):
        '''Reload all agents from the database.'''
        
        logger.info("Loading agents...")
        self.agents.clear()
        for row in self.db.load_agents():
            config = json.loads(row.config)
            agent = self.agent_type(row.type)(
                row.rowid, row.name, row.description, row.ring, config
            )
            self.agents[agent.id] = agent
        
        if len(self.agents) == 0:
            logger.info(f"No agents: Initializing...")
            
            self.create_agent("System")
            self.create_agent("User")
            self.create_agent("Supervisor")
        
        self.agent = self.agents[1]
    
    def load_subcriptions(self):
        '''Reload all subscriptions from the database.'''
        
        logger.debug("Loading subscriptions...")
        self.subs.clear()
        for sub in self.db.load_subscriptions():
            self.subs[sub.channel].add(self.agents[sub.agent_id])
    
    async def start(self):
        await self.load_agents()
        self.load_subcriptions()
        
        for agent in self.agents.values():
            self.taskgroup.create_task(agent.run(self))
    
    def exit(self):
        current = None
        for task in self.taskgroup._tasks:
            if task == asyncio.current_task():
                current = task
            if task.done() or task == asyncio.current_task():
                continue
            task.cancel()
        
        if current:
            current.cancel()

async def start(dbpath: str, tools: dict[str, type[Tool]]):
    '''
    Entrypoint for the kernel, initializes everything so we don't have to
    constantly check if things are initialized.
    '''
    api_key = read_file("private/api.key")
    
    with patch_stdout():
        async with connect(api_key) as client:
            with sqlite3.Connection(dbpath) as sql:
                async with asyncio.TaskGroup() as tg:
                    db = Database(sql)
                    system = Kernel(tg, db, client, tools)
                    tg.create_task(system.start())