import asyncio
import sqlite3
import openai

from prompt_toolkit.patch_stdout import patch_stdout
from prompt_toolkit import PromptSession
from prompt_toolkit.formatted_text import FormattedText

from db import AgentRow
from util import logger, typename, read_file
from connector import ActionRequired, TextContent, ImageContent, AssistantId, ThreadId, RunId
from typedef import override, Any, Optional
from system import Message, Agent, Agent, Kernel
from tool import Tool

@Agent.register
class System(Agent):
    ring = 0
    name = "System"
    description = "Proxy agent for the system kernel"
    
    @override
    async def run(self, system: 'Kernel'):
        while True:
            async for msg in self.pull():
                print("SYSTEM", msg)
    
    @override
    async def on_destroy(self, system: 'Kernel'):
        '''Callback for when the agent is destroyed. Allows alerting subscribers.'''

@Agent.register
class GPTAgent(Agent):
    '''Self-contained thread and assistant.'''
    
    assistant_id: AssistantId
    '''Openai API assistant.'''
    
    thread_id: ThreadId
    '''Openai API thread.'''
    
    run_id: Optional[RunId]
    '''Openai API run.'''
    
    tools: list[str]|dict[str, Tool]
    '''Instantiated tools available to the agent.'''
    
    def __init__(self,
        id: AgentRow.primary_key,
        name: str,
        description: str,
        ring: int,
        config: dict
    ):
        if config is None:
            config = {}
        super().__init__(id, name, description, ring, config)
        
        self.assistant_id = config.get("assistant") or self.assistant_id
        self.thread_id = config.get('thread') or getattr(self, "thread", None) # type: ignore
        self.run_id = None
        tools = config.get('tools')
        if tools is None:
            tools = getattr(self, "tools", [])
        self.tools = tools
        #self.tools = getattr(self, "tools", []) if tools is None else tools
    
    @override
    def state(self):
        assert isinstance(self.tools, dict)
        return {
            "tools": {
                name: tool.state()
                for name, tool in self.tools.items()
            }
        }
    
    @override
    async def init(self, kernel: Kernel, state: dict):
        # Initialize tools
        self.tools = {
            tool: kernel.tools[tool](kernel, self)
            for tool in self.tools
        }
        last = None
        async for run in kernel.openai.thread(self.thread_id).run.iter():
            last = run
        
        if last and last.completed_at is None:
            self.run_id = last.id
            logger.info(f"Resuming {self.run_id}")
    
    @override
    async def run(self, kernel: Kernel):
        '''Run the agent thread in an infinite loop.'''
        
        assert isinstance(self.tools, dict)
        
        # Initialize
        assistant = kernel.openai.assistant(self.assistant_id)
        if self.thread_id is None:
            # Create a new thread
            self.thread_id = (await kernel.openai.thread.create()).id
            kernel.update_config(self, {
                "thread": self.thread_id
            })
        thread = kernel.openai.thread(self.thread_id)
        
        while True:
            while self.pause_signal.is_set() or kernel.pause_signal.is_set():
                await self.until_unpaused()
                await kernel.until_unpaused()
            logger.debug(f"Resume: {self.name}")
            
            # Consume all pushed messages, adding to the thread
            last = None
            async for msg in self.pull():
                last = await thread.message.create(str(msg))
            logger.debug(f"Messages: {self.name}")
            
            # Got a poke, pick the most recent message
            if last is None:
                msg = await anext(thread.message.list(order="desc"))
                last = thread.message(msg.id)
            
            # Support recovering an existing run
            if self.run_id is None:
                runit = await thread.run.create(assistant.id)
                self.run_id = runit.id
                kernel.add_state(self)
            else:
                runit = thread.run(self.run_id)
            
            async with runit as run:
                step = await anext(run)
                # Should really be `while True` but then code is marked unreachable
                while step is not None:
                    match step:
                        case ActionRequired(func, ps):
                            if func not in self.tools:
                                content = f"ERROR: {func!r} is not an available tool (try one of: {list(self.tools.keys())})"
                            else:
                                try:
                                    logger.info(f"Function call {func} {ps}")
                                    args = await kernel.parse_json(ps)
                                    content = repr(await self.tools[func](**args))
                                except KeyboardInterrupt:
                                    raise
                                except BaseException as e:
                                    content = f"{typename(e)}: {e.args[0]}"
                            
                            logger.info(f"Return {func}: {content}")
                            step = await run.asend(content)
                        
                        case _:
                            raise TypeError(f"Unknown step: {typename(step)}")
            
            self.run_id = None
            
            # Edge case: Got a poke on a brand new thread
            if last is None:
                continue
            
            # TODO: Edge case, if agent swarm manager is stopped here then the
            #  unnamed channel won't publish to subscribers. To fix, you would
            #  need to keep a journal of API message IDs processed and recover
            #  that journal on init.
            
            # Now retrieve the results
            async for step in thread.message.list(order='asc', after=last.id):
                for content in step.content:
                    match content:
                        case ImageContent(file_id):
                            logger.warn("Image file created:", file_id)
                            pass
                        
                        case TextContent(msg):
                            kernel.publish(self, None, msg)
                        
                        case _:
                            raise TypeError(f"Unknown step type {typename(step)}")
    
    @override
    async def on_destroy(self, system: Kernel):
        await system.openai.thread(self.thread_id).delete()

@Agent.register
class Supervisor(GPTAgent):
    '''Supervising agent of the system.'''
    
    ring = 1
    name = "Supervisor"
    description = str(__doc__)
    instructions = read_file("supervisor.md")
    assistant_id = "asst_6SnQRYaBJOptljPpvJTvOd5o"
    tools = ["subscribe", "unsubscribe", "publish", "create", "destroy", 'python', 'shell']
    
    @override
    async def init(self, kernel: Kernel, state: dict):
        await super().init(kernel, state)
        assert isinstance(self.tools, dict)
        
        python = state.get("python")
        if python is not None:
            self.tools['python'].load_state(python)

def print_sql(cursor: sqlite3.Cursor, rows: list[sqlite3.Row]):
    '''Print the results of a SQL query.'''
    
    if len(rows) == 0:
        print("empty set")
        return
    
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
        print('\n', len(rows), "rows in set")

@Agent.register
class User(Agent):
    '''User proxy agent.'''
    
    ring = 0
    name = "User"
    description = str(__doc__)
    
    def sql_command(self, kernel, cmd, code):
        try:
            match cmd:
                case "sql":
                    with kernel.db.transaction() as cursor:
                        rows = cursor.execute(code).fetchall()
                        print_sql(cursor, rows)
                
                case "select":
                    with kernel.db.transaction() as cursor:
                        rows = cursor.execute(f"SELECT {code}").fetchall()
                        print_sql(cursor, rows)
        except sqlite3.Error as e:
            print(e)
    
    async def openai_command(self, kernel, cmd, rest):
        assert kernel.openai is not None
        
        try:
            match [cmd, *rest.split(' ')]:
                case ['thread', thread_id]:
                    if thread_id.startswith("+"):
                        after = thread_id[1:]
                    else:
                        after = None
                    async for step in kernel.openai.thread(thread_id).message.list(order="asc", after=after):
                        for content in step.content:
                            match content:
                                case ImageContent(file_id):
                                    print("* Image file:", file_id)
                                
                                case TextContent(text):
                                    print(f"* {text}")
                
                case ['run', sub, thread_id, *rest]:
                    thread = kernel.openai.thread(thread_id)
                    match (sub, *rest):
                        case ['list']:
                            ls = []
                            async for run in thread.run.iter():
                                ls.append(run.id)
                            
                            for run in reversed(ls):
                                print("*", run.id)
                        
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
    
    @override
    def push(self, msg: Message):
        print(msg.printable())
    
    async def run(self, kernel: Kernel):
        '''User input agent.'''
        
        tty = PromptSession()
        
        # NOTE: User agent does not respect kernel pausing, otherwise
        #  it would be locked forever.
        
        while True:
            try:
                with patch_stdout():
                    paused = kernel.pause_signal.is_set()
                    icon = "▶️" if paused else "⏸"
                    user = await tty.prompt_async(FormattedText(
                        [('ansiyellow', f'{icon} User> ')]
                    ))
            except asyncio.CancelledError:
                logger.debug("User(): Cancel")
                break
            except KeyboardInterrupt:
                kernel.exit()
                break
            user = user.strip()
            if user == "":
                continue
            
            if not user.startswith("/") or user.startswith("//"):
                if user.startswith("/"):
                    user = user[1:]
                
                kernel.publish(self, "*", user)
            
            elif user == "/" or user.startswith("/#"):
                pass
            
            else:
                cmd, *rest = user[1:].split(' ', 1)
                match cmd:
                    case "help":
                        print("# help quit sql select thread run{list, get, cancel} pause resume{all}/unpause{all}")
                    
                    case "quit": kernel.exit()
                    case "sql"|"select":
                        self.sql_command(kernel, cmd, rest[0])
                    
                    case "thread"|"run":
                        await self.openai_command(kernel, cmd, rest[0])
                    
                    case "pause"|'resume':
                        if len(rest) == 0:
                            getattr(kernel, cmd)()
                        elif rest[0] == 'all':
                            for agent in kernel.agents.values():
                                getattr(agent, cmd)()
                        else:
                            getattr(kernel.agents[int(rest[0], 16)], cmd)()
                    
                    case "msg":
                        if len(rest) == 0:
                            print("Usage: /msg <channel> <message>")
                        else:
                            chan, msg = rest[0].split(' ', 1)
                            kernel.publish(self, chan, msg)
                    
                    case "poke":
                        if len(rest) == 0:
                            print("Usage: /poke <id>")
                        else:
                            kernel.agents[int(rest[0], 16)].poke()
                    
                    case "subs":
                        for chan, subs in kernel.subs.items():
                            print(chan, ":", ' / '.join(sub.name for sub in subs))
                    
                    case _:
                        print("Unknown command", cmd)