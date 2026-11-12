# ReAct Agents

ReAct (Reasoning and Acting) is an agent pattern introduced by Yao et al. in 2022. The model interleaves reasoning steps with actions such as tool calls, and observes the result of every action before deciding what to do next.

## The loop

A ReAct agent repeats four phases: plan, act, observe and reflect. In the plan phase the model decides the next action. In the act phase the runtime executes the requested tool calls, often in parallel. In the observe phase the tool results are appended to the conversation as tool messages. Reflection lets the agent notice when it is stuck, for example when it repeats the same tool call with the same arguments.

## Safeguards

Production agents need a hard limit on the number of steps, a timeout for the whole run, and a token budget for the context window. Without a step limit a confused model can loop forever and burn tokens.

## Native tool calling

Modern models such as Qwen 2.5 and Llama 3.1 support native tool calling: the model returns structured tool calls with JSON arguments instead of free text that must be parsed with regular expressions. Native tool calling is more reliable than text-based ReAct prompting.
