"""Specialized agents (Researcher, Coder, Reviewer, Planner), A2A messaging and team patterns."""

from agentcore.agents.a2a import A2AMessage, A2AMessageType, MessageBus, agent_handler
from agentcore.agents.base import AgentOutput, SpecializedAgent, extract_json
from agentcore.agents.patterns import ManagerWorker, Pipeline, TeamResult, peer_review
from agentcore.agents.specialists import (
    CoderAgent,
    Plan,
    PlannerAgent,
    PlanTask,
    ResearcherAgent,
    ReviewerAgent,
    ReviewIssue,
    ReviewResult,
)

__all__ = [
    "A2AMessage",
    "A2AMessageType",
    "AgentOutput",
    "CoderAgent",
    "ManagerWorker",
    "MessageBus",
    "Pipeline",
    "Plan",
    "PlanTask",
    "PlannerAgent",
    "ResearcherAgent",
    "ReviewIssue",
    "ReviewResult",
    "ReviewerAgent",
    "SpecializedAgent",
    "TeamResult",
    "agent_handler",
    "extract_json",
    "peer_review",
]
