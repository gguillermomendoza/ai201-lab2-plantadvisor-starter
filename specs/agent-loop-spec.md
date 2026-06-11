# Spec: `run_agent()`

**File:** `agent.py`
**Status:** Partially pre-filled — complete the two blank fields before implementing

---

## Purpose

Orchestrate a single conversational turn for the Plant Advisor agent. Given a user message and the conversation history, call the LLM with available tools, execute any tool calls the LLM requests, and return the final text response.

This is the core of what makes Plant Advisor an *agent* rather than a simple chatbot: the ability to decide which tools to call, use their results to inform its response, and loop until it has everything it needs.

---

## Input / Output Contract

**Inputs:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `user_message` | `str` | The user's current message |
| `history` | `list` | Gradio conversation history — list of `[user_msg, assistant_msg]` pairs |

**Output:** `str`

The agent's final text response for this turn. Should never be empty — if something goes wrong, return a user-readable fallback message.

---

## Design Decisions

*Read `specs/system-design.md` (especially the "How the Groq Tool Calling API Works" section) before reviewing these. Complete the two blank fields before writing any code.*

---

### Messages list structure

The messages list must start with the system prompt, then replay the conversation
history, then add the new user message. Gradio history is a list of `[user, assistant]`
pairs — convert each pair to two API-format dicts:

```python
messages = [{"role": "system", "content": SYSTEM_PROMPT}]

for user_msg, assistant_msg in history:
    messages.append({"role": "user", "content": user_msg})
    if assistant_msg:
        messages.append({"role": "assistant", "content": assistant_msg})

messages.append({"role": "user", "content": user_message})
```

---

### Initial LLM call

Pass the model, the messages list, the tool definitions, and `tool_choice="auto"`
so the LLM can decide whether to call a tool or respond directly:

```python
response = client.chat.completions.create(
    model=LLM_MODEL,
    messages=messages,
    tools=TOOL_DEFINITIONS,
    tool_choice="auto",
)
```

---

### Detecting tool calls in the response

The response object has a `choices` list. Index 0 gives the assistant message.
Check its `tool_calls` attribute — if it's truthy, the LLM wants to call tools:

```python
assistant_message = response.choices[0].message

if not assistant_message.tool_calls:
    # No tool calls — LLM has a final answer
    ...
```

---

### Appending the assistant message

When there are tool calls, append the full assistant message object to `messages`
**before** appending any tool results. The API requires this ordering — a tool
result message must immediately follow the assistant message that requested it:

```python
messages.append(assistant_message)  # must come first
```

---

### Executing and appending tool results

For each tool call, extract the name and arguments, call `dispatch_tool()`, and
append the result as a `"tool"` role message. The `tool_call_id` links this result
back to the specific tool call that requested it:

```python
for tool_call in assistant_message.tool_calls:
    tool_name = tool_call.function.name
    tool_args = json.loads(tool_call.function.arguments)
    tool_result = dispatch_tool(tool_name, tool_args)

    messages.append({
        "role": "tool",
        "tool_call_id": tool_call.id,
        "content": tool_result,
    })
```

---

### Loop termination conditions

*The loop should stop when: (a) the LLM returns a response with no tool calls, OR (b) the MAX_TOOL_ROUNDS limit is reached. Describe how you will detect each condition and what you will return in each case.*

```
(a) After each LLM call, read response.choices[0].message. If its `tool_calls`
    attribute is falsy (None / empty list), the LLM has produced a final answer.
    Break out of the loop and return message.content.

(b) The loop body runs at most MAX_TOOL_ROUNDS times (a `for _ in range(...)`).
    If we finish the last iteration and the LLM is STILL asking for tools, we've
    hit the safety cap. Make one final LLM call with NO tools (tool_choice
    unavailable) to force a plain-text answer, and return that content. If even
    that is empty, return a user-readable fallback string so output is never empty.
```

---

### Extracting the final text response

*Once the loop exits because there are no more tool calls, how do you extract the text content from the response object? What field holds the string you should return?*

```
The text lives at response.choices[0].message.content — a plain string. Once the
loop exits on the no-tool-calls condition, return that `.content`. Guard against a
None/empty content with a fallback string so run_agent() never returns an empty
response.
```

---

## Implementation Notes

*Fill this in after implementing and testing.*

**Trace of a working agent turn (what tools were called and in what order):**

```
Query: "What should I do for my pothos this winter?"
Round 1 tool calls (both in ONE assistant message — parallel tool calls):
    lookup_plant({"plant_name": "pothos"})
    get_seasonal_conditions({"season": "winter"})
Round 2: no tool calls — LLM produced the final answer.
Final response: Grounded pothos winter care — water ~every 2–4 weeks (less than
the usual 1–2), more bright indirect light, hold off on fertilizer. Cites the
care data, combining the plant entry with the winter seasonal context.
```

**What happens when you ask about a plant that isn't in the database?**

```
lookup_plant returns {"found": false, ...} with the message listing the available
plants. The LLM reads that message and, instead of inventing care data, explains
the plant wasn't found and asks the user to clarify/specify (e.g. for "bonsai
tree" it noted bonsai is a technique, not a species, and asked which tree).
Graceful degradation works as designed.
```

**One thing about the tool call API that surprised you:**

```
Two things:
1. The LLM can request MULTIPLE tools in a SINGLE assistant message (parallel
   tool calls), so you must loop over assistant_message.tool_calls and append a
   tool-result message for EACH one before calling the LLM again — appending only
   the first would break the assistant/tool message pairing the API requires.
2. The model (llama-3.3-70b on Groq) occasionally emits malformed tool-call
   syntax and Groq returns a 400 "tool_use_failed" instead of a normal response.
   It's intermittent — a retry succeeds. The try/except fallback keeps run_agent
   from crashing when this happens.
```
