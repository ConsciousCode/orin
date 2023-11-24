## Architecture
```mermaid
classDiagram
    class Kernel {
        taskgroup: TaskGroup
        db: Database
        ope
    }
    class Archetype {
        
    }
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
    class Agent {
        
    }
    class Daemon {
        
    }
    class Assistant {
        
    }
    class Servitor {
        
    }
    class UserAgent {
        
    }
    class SystemAgent {
        
    }
    
    Agent --> System
    Archetype <|-- Assistant
    Agent <|-- Daemon
    Agent <|-- Servitor
    Agent <|-- UserAgent
    Agent <|-- SystemAgent
```