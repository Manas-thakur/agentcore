"""AgentCore - a from-scratch agentic AI platform.

Quick start::

    from agentcore import Agent, create_model
    from agentcore.tools import calculator

    agent = Agent(create_model("mock"), tools=[calculator])
    print(agent.run_sync("What is 17 * 23 + 4?").output)
"""

from agentcore.runtime import Agent, AgentConfig, AgentResult, create_model
from agentcore.tools import Tool, ToolRegistry, tool
from agentcore.types import ChatResponse, Message, ToolCall, Usage

__version__ = "0.3.0"

__all__ = [
    "Agent",
    "AgentConfig",
    "AgentResult",
    "ChatResponse",
    "Message",
    "Tool",
    "ToolCall",
    "ToolRegistry",
    "Usage",
    "__version__",
    "create_model",
    "tool",
]
