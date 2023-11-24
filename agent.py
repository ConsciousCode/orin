import asyncio
import sqlite3
import openai

from prompt_toolkit.patch_stdout import patch_stdout
from prompt_toolkit import PromptSession
from prompt_toolkit.formatted_text import FormattedText

from .db import AgentRow, ArchetypeRow
from .util import logger, typename
from .connector import ActionRequired, TextContent, ImageContent, AssistantId, ThreadId
from .typing import override, Any
from .system import Message, Agent, Agent, Kernel
from .tool import Tool

class System(Agent):
    ring = 0
    name = "System"
    description = "Proxy agent for the system kernel"
    
    @override
    async def run(self, system: 'Kernel'):
        while True:
            async for msg in self.pull():
                # TODO
                pass        
    
    @override
    async def on_destroy(self, system: 'Kernel'):
        '''Callback for when the agent is destroyed. Allows alerting subscribers.'''

class GPTAgent(Agent):
    '''Self-contained thread and assistant.'''
    
    thread: ThreadId
    '''Openai API thread.'''
    
    tools: dict[str, Tool]
    '''Instantiated tools available to the agent.'''
    
    msgq: asyncio.Queue[Message]
    '''Pending messages to be processed.'''
    
    def __init__(self,
        id: AgentRow.primary_key,
        name: str,
        description: str,
        ring: int,
        config: Any
    ):
        super().__init__(id, name, description, ring, config)
        
        self.thread = config['thread']
        self.tools = config['tools']
        self.msgq = asyncio.Queue()
    
    @override
    async def run(self, system: Kernel):
        '''Run the agent thread in an infinite loop.'''
        
        # Initialize
        assistant = await GPTAssistant.get(system, self.config['assistant'])
        thread = system.openai.thread(self.thread)
        
        while True:
            last = None
            async for msg in self.pull():
                last = await thread.message.create(str(msg))
            assert last is not None
            
            print("Begin thread")
            async with await thread.run.create(assistant.api_id) as run:
                print("Run start")
                async for step in run:
                    print("Step", step)
                    match step:
                        case ActionRequired(func, ps):
                            if func not in self.tools:
                                content = f"ERROR: {func!r} is not an available tool (try one of: {list(self.tools.keys())})"
                            else:
                                try:
                                    args = await system.parse_json(ps)
                                    content = repr(self.tools[func](**args))
                                except Exception as e:
                                    content = f"{typename(e)}: {e.args[0]}"
                            
                            run.asend(content)
                        
                        case _:
                            raise TypeError(f"Unknown step: {typename(step)}")
                
                print("Run end")
            
            print("Run finished")
            
            # Now retrieve the results
            async for step in self.thread.message.list(order='asc', after=last.id):
                for content in step.content:
                    match content:
                        case ImageContent(file_id):
                            logger.warn("Image file created:", file_id)
                            pass
                        
                        case TextContent(msg):
                            system.publish(self, self.name, msg)
                            system.publish(self, self.idchan(), msg)
                        
                        case _:
                            raise TypeError(f"Unknown step type {typename(step)}")
    
    @override
    async def on_destroy(self, system: Kernel):
        system.unsubscribe_all(self.idchan())
        await self.thread.delete()
    
    async def create_servitor(self,
        ring: int,
        arch: Archetype,
        name: str,
        description: str,
        instructions: str
    ):
        logger.info(f"Create({ring}, {arch.name!r}, {name!r}, {description!r}, {instructions!r})")
        
        # Create thread API resource
        thread = await self.openai.thread.create()
        
        # Insert into the database
        agent_id = self.db.create_agent(
            thread.id, arch.id, ring, name, description, instructions
        )
        
        # Build the live agent
        agent = object.__new__(Servitor)
        agent.__init__(
            arch, agent_id, ring, self.openai.thread(thread.id), name, description,
            {name: tool(self, agent) for name, tool in arch.tools.items()}
        )
        self.agents[agent.id] = agent
        
        # Subscribe to its own channels
        self.subscribe(agent, agent.name)
        self.subscribe(agent, agent.idchan())
        
        return agent.id

class Supervisor(GPTAgent):
    '''Supervising agent of the system.'''
    
    ring = 1
    name = "Supervisor"
    description = str(__doc__)
    
    #def __init__(self, id, name, description, ring, config: json_value):
    #    super().__init__(id, self.name, self.description, self.ring, config)
    
    @override
    async def load(self):
        pass

def print_sql(cursor: sqlite3.Cursor, rows: list[sqlite3.Row]):
    if cursor.description is not None:
        # Fetch column headers
        headers = [desc[0] for desc in cursor.description]

        # Find the maximum length for each column
        lengths = [max(len(str(cell)) for cell in col) for col in zip(*rows)]
        lengths = [max(len(header), colmax) + 2 for header, colmax in zip(headers, lengths)]
        
        # Create a format string with dynamic padding
        tpl = '|'.join(f"{{:^{length}}}" for length in lengths)
        tpl = f"| {tpl} |"

        print(tpl.format(*headers))
        print(tpl.replace("|", "+").format(*('-'*length for length in lengths)))
        print('\n'.join(tpl.format(*map(str, row)) for row in rows))
    
    if cursor.rowcount >= 0:
        print(cursor.rowcount, "rows affected")
    
    if len(rows) > 0:
        print(len(rows), "rows in set")

class UserAgent(Agent)
    def __init__(self, system: Kernel):
        self.system = system
    
    def sql_command(self, cmd, code):
        assert self.system.db is not None
        
        try:
            match cmd:
                case "sql":
                    with self.system.db.transaction() as cursor:
                        rows = cursor.execute(code).fetchall()
                        print_sql(cursor, rows)
                
                case "select":
                    with self.system.db.transaction() as cursor:
                        rows = cursor.execute(f"SELECT {code}").fetchall()
                        print_sql(cursor, rows)
        except sqlite3.Error as e:
            print(e)
    
    async def openai_command(self, cmd, rest):
        assert self.system.openai is not None
        
        try:
            match [cmd, *rest.split(' ')]:
                case ['thread', thread_id]:
                    if thread_id.startswith("+"):
                        after = thread_id[1:]
                    else:
                        after = None
                    async for step in self.system.openai.thread(thread_id).message.list(order="asc", after=after):
                        for content in step.content:
                            match content:
                                case ImageContent(file_id):
                                    print("* Image file:", file_id)
                                
                                case TextContent(text):
                                    print(f"* {text}")
                
                case ['run', sub, thread_id, *rest]:
                    thread = self.system.openai.thread(thread_id)
                    match (sub, *rest):
                        case ['list']:
                            async for run in thread.run.iter():
                                print(run)
                        
                        case ['get', str(run)]:
                            print(await thread.run(run).retrieve())
                        
                        case ['cancel', str(run)]:
                            await thread.run(run).cancel()
                        
                        case _:
                            print(f"Unknown subcommand {sub}")
                
                case _:
                    print("Invalid command")
        
        except openai.APIError as e:
            logger.error(f"{typename(e)}: {e.message}")

    async def run(self, system: Kernel):
        '''User input agent.'''
        
        tty = PromptSession()
        
        while True:
            #logger.debug("UserAgent(): Loop")
            try:
                with patch_stdout():
                    user = await tty.prompt_async(FormattedText([('ansiyellow', 'User> ')]))
            except asyncio.CancelledError:
                logger.debug("UserAgent(): Cancel")
                break
            user = user.strip()
            if user == "":
                continue
            
            if user.startswith("/"):
                assert system.db is not None
                assert system.openai is not None
                
                cmd, *rest = user[1:].split(' ', 1)
                match cmd:
                    case "help":
                        print("help quit sql select thread")
                    
                    case "quit": break
                    case "sql"|"select":
                        self.sql_command(cmd, rest[0])
                    
                    case "thread"|"run":
                        await self.openai_command(cmd, rest[0])
                    
                    case _:
                        print("Unknown command", cmd)
            else:
                logger.debug("Before publish")
                system.publish(system.agent, "*", user)
                logger.debug("After publish")
        
        print("UserAgent.run End")