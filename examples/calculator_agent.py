"""A tool-using ReAct agent with a safe calculator.

Run offline (deterministic mock model):
    python examples/calculator_agent.py --model mock
With a local model:
    python examples/calculator_agent.py --model ollama:qwen2.5:7b "What is 2**20 - 1?"
"""

from __future__ import annotations

import argparse

from agentcore import Agent, create_model
from agentcore.obs import configure_tracing
from agentcore.runtime import AgentEvent
from agentcore.tools import calculator, tool


@tool
def unit_convert(value: float, unit: str) -> str:
    """Convert a value between km and miles.

    Args:
        value: The numeric value to convert.
        unit: Either "km_to_miles" or "miles_to_km".
    """
    factor = 0.621371 if unit == "km_to_miles" else 1 / 0.621371
    return f"{value * factor:.3f}"


def print_event(ev: AgentEvent) -> None:
    if ev.type == "tool_start":
        print(f"  -> {ev.data['name']}({ev.data['arguments']})")
    elif ev.type == "tool_end":
        status = "ok" if ev.data["success"] else "error"
        print(f"  <- [{status}] {ev.data['output']}")
    elif ev.type == "token":
        print(ev.data["content"], end="", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("question", nargs="?", default="What is (17 * 23 + 4) / 3?")
    parser.add_argument(
        "--model", default="auto", help="mock | auto | ollama:<model> | openai:<model>"
    )
    parser.add_argument("--stream", action="store_true", help="stream tokens (real models)")
    args = parser.parse_args()

    configure_tracing(".agentcore/traces")
    model = create_model(args.model, verbose=True)
    agent = Agent(
        model, tools=[calculator, unit_convert], name="calculator", max_steps=6, stream=args.stream
    )
    agent.on(print_event)

    print(f"Q: {args.question}")
    result = agent.run_sync(args.question)
    print(f"\nA: {result.output}")
    print(
        f"[{result.stop_reason}] steps={result.steps} tokens={result.usage.total_tokens} "
        f"time={result.duration_ms:.0f}ms trace={result.trace_id}"
    )


if __name__ == "__main__":
    main()
