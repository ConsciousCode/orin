/* Identify agents. Append-only */
CREATE TABLE IF NOT EXISTS agent (
    /* rowid */
    type TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    deleted_at INTEGER,
    ring INTEGER NOT NULL,
    name TEXT NOT NULL,
    description TEXT NOT NULL,
    config TEXT NOT NULL
);

/*
 * Agent channel subscriptions. Mutable, don't need to reconstruct
 *  subscription states at any given time, only message channels.
 */
CREATE TABLE IF NOT EXISTS subscription (
    channel TEXT NOT NULL,
    agent_id INTEGER NOT NULL,
    
    PRIMARY KEY (channel, agent_id),
    
    FOREIGN KEY (agent_id) REFERENCES agent(id)
) WITHOUT ROWID;

/* Store messages from channels. Append-only. */
CREATE TABLE IF NOT EXISTS message (
    /* rowid */
    role TEXT NOT NULL,
    agent_id INTEGER NOT NULL,
    content TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL,
    
    FOREIGN KEY (agent_id) REFERENCES agent(id)
);

/* Keep track of which agents received messages. Append-only. */
CREATE TABLE IF NOT EXISTS push (
    channel TEXT NOT NULL,
    agent_id INTEGER NOT NULL,
    message_id INTEGER NOT NULL,
    
    PRIMARY KEY (agent_id, message_id),
    
    FOREIGN KEY (agent_id) REFERENCES agent(id),
    FOREIGN KEY (message_id) REFERENCES message(id)
) WITHOUT ROWID;

/* Persistent agent states */
CREATE TABLE IF NOT EXISTS state (
    /* rowid */
    created_at INTEGER NOT NULL,
    agent_id INTEGER NOT NULL,
    data BLOB NOT NULL,
    
    FOREIGN KEY (agent_id) REFERENCES agent(id)
);