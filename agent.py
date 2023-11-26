import asyncio
import sqlite3
import openai

from prompt_toolkit.patch_stdout import patch_stdout
from prompt_toolkit import PromptSession
from prompt_toolkit.formatted_text import FormattedText

from db import AgentRow
from util import logger, typename, read_file
from connector import ActionRequired, TextContent, ImageContent, AssistantId, ThreadId
from typedef import override, Any
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
                # TODO
                pass        
    
    @override
    async def on_destroy(self, system: 'Kernel'):
        '''Callback for when the agent is destroyed. Allows alerting subscribers.'''

class GPTAgent(Agent):
    '''Self-contained thread and assistant.'''
    
    assistant: AssistantId
    '''Openai API assistant.'''
    
    thread: ThreadId
    '''Openai API thread.'''
    
    tools: list[str]|dict[str, Tool]
    '''Instantiated tools available to the agent.'''
    
    def __init__(self,
        id: AgentRow.primary_key,
        name: str,
        description: str,
        ring: int,
        config: Any
    ):
        if config is None:
            config = {}
        super().__init__(id, name, description, ring, config)
        
        self.assistant = config.get("assistant") or self.assistant
        self.thread = config.get('thread') or getattr(self, "thread", None) # type: ignore
        self.tools = config.get('tools') or self.tools
    
    @override
    async def run(self, kernel: Kernel):
        '''Run the agent thread in an infinite loop.'''
        
        # Initialize
        assistant = kernel.openai.assistant(self.assistant)
        if self.thread is None:
            # Create a new thread
            thread_id = (await kernel.openai.thread.create()).id
            self.thread = thread_id
            kernel.update_config(self, {
                "thread": self.thread
            })
        thread = kernel.openai.thread(self.thread)
        
        if isinstance(self.tools, list):
            self.tools = {
                tool: kernel.tools[tool](kernel, self)
                for tool in self.tools
            }
        
        while True:
            last = None
            async for msg in self.pull():
                last = await thread.message.create(str(msg))
            assert last is not None
            
            async with await thread.run.create(assistant.id) as run:
                async for step in run:
                    match step:
                        case ActionRequired(func, ps):
                            if func not in self.tools:
                                content = f"ERROR: {func!r} is not an available tool (try one of: {list(self.tools.keys())})"
                            else:
                                try:
                                    print("Function call:", func, ps)
                                    args = await kernel.parse_json(ps)
                                    content = repr(self.tools[func](**args))
                                except Exception as e:
                                    content = f"{typename(e)}: {e.args[0]}"
                            
                            print("Return:", content)
                            run.asend(content)
                        
                        case _:
                            raise TypeError(f"Unknown step: {typename(step)}")
            
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
        await system.openai.thread(self.thread).delete()

@Agent.register
class Supervisor(GPTAgent):
    '''Supervising agent of the system.'''
    
    ring = 1
    name = "Supervisor"
    description = str(__doc__)
    instructions = read_file("supervisor.md")
    assistant = "asst_6SnQRYaBJOptljPpvJTvOd5o"
    tools = ["subscribe", "unsubscribe", "publish"]

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

@Agent.register
class User(Agent):
    '''User proxy agent.'''
    
    ring = 0
    name = "User"
    description = str(__doc__)
    
    def sql_command(self, kernel, cmd, code):
        assert kernel.db is not None
        
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
    
    @override
    def push(self, msg: Message):
        print(msg)
    
    async def run(self, kernel: Kernel):
        '''User input agent.'''
        
        tty = PromptSession()
        kernel.subscribe(self, "*")
        
        while True:
            logger.debug("User(): Loop")
            try:
                with patch_stdout():
                    user = await tty.prompt_async(FormattedText([('ansiyellow', 'User> ')]))
            except asyncio.CancelledError:
                logger.debug("User(): Cancel")
                break
            except KeyboardInterrupt:
                kernel.exit()
                break
            user = user.strip()
            if user == "":
                continue
            
            if user.startswith("/"):
                assert kernel.db is not None
                assert kernel.openai is not None
                
                cmd, *rest = user[1:].split(' ', 1)
                match cmd:
                    case "help":
                        print("help quit sql select thread")
                    
                    case "quit": kernel.exit()
                    case "sql"|"select":
                        self.sql_command(kernel, cmd, rest[0])
                    
                    case "thread"|"run":
                        await self.openai_command(kernel, cmd, rest[0])
                    
                    case _:
                        print("Unknown command", cmd)
            else:
                logger.debug("Before publish")
                kernel.publish(self, "*", user)
                logger.debug("After publish")