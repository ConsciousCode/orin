import io
from contextlib import redirect_stdout, redirect_stderr
import traceback
import subprocess

from .typedef import override
from .system import Tool, Kernel, Agent

class Python(Tool):
    '''
    Execute arbitrary python code in a persistent environment. Returns stdout.
    
    The agent swarm system kernel and agent are available as globals.
    '''
    
    parameters = {
        "code": {"type": "string", "description": "Python code to execute."}
    }
    
    def __init__(self, kernel: Kernel, agent: Agent):
        super().__init__(kernel, agent)
        self.globals = {
            "__name__": agent.name,
            "__doc__": agent.description,
            "__package__": None,
            "__builtins__": __builtins__,
            "__annotations__": None,
            "kernel": kernel,
            "agent": agent
        }
        self.env = {}
    
    @override
    def load_state(self, state: object):
        if state is not None:
            assert isinstance(state, dict)
            self.env = state
    
    async def __call__(self, code):
        with redirect_stdout(io.StringIO()) as f:
            with redirect_stderr(f):
                try:
                    exec(code, self.globals, self.env)
                except Exception as e:
                    traceback.print_exception(e, file=f)
        
        # Persist environment state
        self.kernel.add_state(self.agent)
        
        return f.getvalue()

class Shell(Tool):
    '''Execute shell code. Will timeout if it takes more than 3 seconds.'''
    
    # TODO: It may be worthwhile to have shell agents which use the Agent push system
    
    parameters = {
        "code": {"type": "string", "description": "Bash code to execute."}
    }
    
    async def __call__(self, code):
        return subprocess.run(["bash", "-c", code], capture_output=True, timeout=3)

class Create(Tool):
    '''Create a new agent.'''
    
    parameters = {
        "ring": {"type": "integer", "description": "Ring of the new agent."},
        "model": {"type": "string", "description": "OpenAI API model to use."},
        "name": {"type": "string", "description": "Name of the agent."},
        "description": {
            "type": "string",
            "description": "Short description of the agent's responsibilities for other agents."
        },
        "instructions": {
            "type": "string",
            "description": "Full system prompt defining the agent's behavior."
        },
        "tools": {
            "type": "array",
            "items": {"type": "string"},
            "description": "A list of tools to provide the agent."
        }
    }
    
    async def __call__(self, ring, model, name, description, instructions, tools) -> int:
        if ring <= self.agent.ring:
            raise PermissionError("Attempting to create an agent in equal or lower ring")
        
        assistant = await self.kernel.openai.assistant.create(model, name, description, instructions, tools)
        
        thread = await self.kernel.openai.thread.create()
        
        agent = await self.kernel.create_agent("GPTAgent", ring, name, description, {
            "tools": tools,
            "assistant": assistant.id,
            "thread": thread.id
        })
        return agent.id

class Destroy(Tool):
    '''Destroy an existing agent.'''
    
    parameters = {
        "agent": {"type": "integer", "description": "The agent's id."}
    }
    
    async def __call__(self, agent):
        if self.kernel.agents[agent].ring <= self.agent.ring: 
            raise PermissionError("Attempting to destroy an agent in equal or higher ring")
        
        if not await self.kernel.destroy(agent):
            return {"warning": "Attempted to destroy nonexistent agent."}

class Subscribe(Tool):
    '''Subscribe to a channel.'''
    
    parameters = {
        "channel": {"type": "string", "description": "Name of the channel to subscribe to."}
    }
    
    async def __call__(self, channel):
        self.kernel.subscribe(self.agent, channel)

class Unsubscribe(Tool):
    '''Unsubscribe to a channel.'''
    
    parameters = {
        "channel": {"type": "string", "description": "Name of the channel to unsubscribe from."}
    }
    
    async def __call__(self, channel):
        self.kernel.unsubscribe(self.agent, channel)

class Publish(Tool):
    '''Publish a message to a channel.'''
    
    parameters = {
        "channel": {"type": "string", "description": "Channel to publish to."},
        "message": {"type": "string", "description": "Message to publish."}
    }
    
    async def __call__(self, channel, message):
        if not self.kernel.publish(self.agent, channel, message):
            return {"warning": "Published to channel with no subscribers."}