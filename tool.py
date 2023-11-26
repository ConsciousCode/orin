import io
from contextlib import redirect_stdout
import inspect

class Tool:
    parameters: dict
    
    def __init__(self, kernel, agent):
        self.kernel = kernel
        self.agent = agent
    
    def __call__(self, **kwargs):
        ...
    
    @classmethod
    def to_schema(cls):
        return {
            "type": "function",
            "function": {
                "name": cls.__name__.lower(),
                "description": inspect.getdoc(cls),
                "parameters": {
                    "type": "object",
                    "properties": cls.parameters,
                    "required": list(cls.parameters.keys())
                }
            }
        }
"""
class Exec(Tool):
    '''Execute arbitrary python code in a persistent environment. Returns stdout.'''
    
    parameters = {
        "code": {"type": "string", "description": "Python code to execute."}
    }
    
    def __init__(self, system, agent):
        super().__init__(system, agent)
        self.env = {}
    
    def __call__(self, code):
        with redirect_stdout(io.StringIO()) as f:
            exec(code, globals(), self.env)
        
        self.system.push_state(self.agent, self.env)
        
        return f.getvalue()
"""
class Create(Tool):
    '''Create a new agent.'''
    
    parameters = {
        "ring": {"type": "integer", "description": "Ring of the new agent."},
        "name": {"type": "string", "description": "Name of the agent."},
        "description": {
            "type": "string",
            "description": "Short description of the agent's responsibilities for other agents."
        },
        "system_prompt": {
            "type": "string",
            "description": "Full system prompt defining the agent's behavior."
        },
        "tools": {
            "type": "array",
            "items": {"type": "string"},
            "description": "A list of already instantiated tools to provide to the user."
        }
    }
    
    def __call__(self, ring, name, description, system_prompt, tools):
        if self.agent.ring >= ring:
            raise PermissionError("Attempting to create an agent in equal or lower ring")
        
        return self.kernel.create_agent(ring, name, description, system_prompt, tools)

class Destroy(Tool):
    '''Destroy an existing name.'''
    
    parameters = {
        "agent": {"type": "integer", "description": "The agent's id."}
    }
    
    def __call__(self, agent):
        if not self.kernel.destroy(self.agent, agent):
            return {"warning": "Attempted to destroy nonexistent agent."}

class Subscribe(Tool):
    '''Subscribe to a channel.'''
    
    parameters = {
        "channel": {"type": "string", "description": "Name of the channel to subscribe to."}
    }
    
    def __call__(self, channel):
        self.kernel.subscribe(self.agent, channel)

class Unsubscribe(Tool):
    '''Unsubscribe to a channel.'''
    
    parameters = {
        "channel": {"type": "string", "description": "Name of the channel to unsubscribe from."}
    }
    
    def __call__(self, channel):
        self.kernel.unsubscribe(self.agent, channel)

class Publish(Tool):
    '''Publish a message to a channel.'''
    
    parameters = {
        "channel": {"type": "string", "description": "Channel to publish to."},
        "message": {"type": "string", "description": "Message to publish."}
    }
    
    def __call__(self, channel, message):
        if not self.kernel.publish(self.agent, channel, message):
            return {"warning": "Published to channel with no subscribers."}