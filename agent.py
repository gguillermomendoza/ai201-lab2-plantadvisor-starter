import json
from groq import Groq, BadRequestError
from config import GROQ_API_KEY, LLM_MODEL, MAX_TOOL_ROUNDS
from tools import lookup_plant, get_seasonal_conditions

# How many times to retry a single LLM call that fails with a transient,
# model-side malformed-tool-call error (Groq "tool_use_failed"). The model
# occasionally emits invalid tool syntax; a fresh attempt usually succeeds.
_MAX_LLM_RETRIES = 2

_client = Groq(api_key=GROQ_API_KEY)

# ──────────────────────────────────────────────
# Tool definitions
#
# These are the schemas that tell the LLM what tools are available and how to
# call them. The LLM reads these descriptions and decides when (and how) to use
# each tool. They're already complete — your job is to implement the tool
# functions in tools.py and the agent loop below.
# ──────────────────────────────────────────────

TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "lookup_plant",
            "description": (
                "Look up care information for a specific houseplant by name. "
                "Returns detailed watering, light, humidity, and temperature requirements. "
                "Use this whenever the user asks about a specific plant."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "plant_name": {
                        "type": "string",
                        "description": "The plant name to look up. Can be a common name, scientific name, or nickname (e.g., 'pothos', 'devil's ivy', 'Monstera deliciosa').",
                    }
                },
                "required": ["plant_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_seasonal_conditions",
            "description": (
                "Get seasonal care adjustments for houseplants. "
                "Returns guidance on watering, fertilizing, light, and pests for the current or specified season. "
                "Use this when a user asks a season-specific question, or to complement plant care advice with seasonal context."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "season": {
                        "type": "string",
                        "description": "The season to get care conditions for. If omitted, the current season is detected automatically.",
                        "enum": ["spring", "summer", "fall", "winter"],
                    }
                },
                "required": [],
            },
        },
    },
]

# ──────────────────────────────────────────────
# System prompt
# ──────────────────────────────────────────────

SYSTEM_PROMPT = (
    "You are a knowledgeable and friendly plant care advisor. "
    "Help users care for their houseplants by looking up specific plant information "
    "and current seasonal conditions using your available tools.\n\n"
    "Always use your tools to look up plant-specific information before answering — "
    "don't rely on your general knowledge alone. If a plant isn't in your database, "
    "say so clearly and offer general guidance based on what the user describes.\n\n"
    "Keep your advice practical and specific. Cite the source of your information "
    "when you have it (e.g., 'According to the care data for your monstera...')."
)

# ──────────────────────────────────────────────
# Tool dispatch
#
# This is already complete. It routes tool calls from the LLM to the actual
# Python functions in tools.py, and returns results as JSON strings (which is
# what the Groq API expects for tool results).
# ──────────────────────────────────────────────

def dispatch_tool(tool_name: str, tool_args: dict) -> str:
    """Route a tool call to the correct function and return the result as a JSON string."""
    print(f"  -> Tool call: {tool_name}({tool_args})")
    try:
        if tool_name == "lookup_plant":
            # The model is supposed to send plant_name, but guard against it
            # omitting the required argument so we return data, not a crash.
            result = lookup_plant(tool_args["plant_name"])
        elif tool_name == "get_seasonal_conditions":
            result = get_seasonal_conditions(tool_args.get("season"))
        else:
            result = {"error": f"Unknown tool: {tool_name}"}
    except Exception as e:
        # Any tool-level failure (bad args, data issue) becomes a structured
        # error the LLM can read and recover from, instead of killing the turn.
        result = {"error": f"Tool '{tool_name}' failed: {e}"}
    encoded = json.dumps(result)
    print(f"  <- Result: {encoded[:120]}{'...' if len(encoded) > 120 else ''}")
    return encoded


def _create_completion(**kwargs):
    """
    Wrapper around the Groq completion call that retries the transient
    "tool_use_failed" error — the model sometimes emits malformed tool-call
    syntax and Groq rejects it with a 400. A retry almost always succeeds.
    Other errors are re-raised immediately (no point retrying a bad request).
    """
    for attempt in range(_MAX_LLM_RETRIES + 1):
        try:
            return _client.chat.completions.create(**kwargs)
        except BadRequestError as e:
            transient = "tool_use_failed" in str(e)
            if transient and attempt < _MAX_LLM_RETRIES:
                print(f"  [retry] tool_use_failed (attempt {attempt + 1}); retrying")
                continue
            raise


# ──────────────────────────────────────────────
# Agent loop
# ──────────────────────────────────────────────

def run_agent(user_message: str, history: list) -> str:
    """
    Run the plant care agent for one user turn and return its response.

    TODO — Milestone 2:

    The agent loop follows a specific pattern that you'll implement here. Read
    specs/agent-loop-spec.md carefully before writing any code — understand the
    full loop before implementing any part of it.

    The loop works like this:
      1. Build a messages list: system prompt + conversation history + new user message
      2. Call the LLM with messages and TOOL_DEFINITIONS
      3. If the response contains tool_calls:
           a. Append the assistant message (with tool_calls) to messages
           b. For each tool call: execute via dispatch_tool(), append the result
           c. Call the LLM again with the updated messages
           d. Repeat until no more tool_calls (or MAX_TOOL_ROUNDS is reached)
      4. Return the final text response

    Key details to get right:
      - The assistant message must be appended BEFORE tool results
      - Tool result messages use role="tool" with a tool_call_id field
      - Append the assistant's message object directly (not just its content)
      - The history format from Gradio: list of [user_message, assistant_message] pairs

    Before writing code, complete specs/agent-loop-spec.md.
    """
    FALLBACK = (
        "Sorry — I ran into trouble answering that. Could you rephrase your "
        "question or tell me which plant you're asking about?"
    )

    # 1. Build the messages list: system prompt + replayed history + new message.
    #
    # Gradio can hand us history in two shapes depending on the ChatInterface
    # config. app.py uses type="messages", which passes a flat list of
    # {"role", "content"} dicts. The older default passes [user, assistant]
    # pairs. Support both so the agent never loses conversation context.
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    for item in history:
        if isinstance(item, dict):
            # messages format — append role/content turns directly
            if item.get("role") and item.get("content"):
                messages.append({"role": item["role"], "content": item["content"]})
        else:
            # pairs format — [user_msg, assistant_msg]
            user_msg, assistant_msg = item
            messages.append({"role": "user", "content": user_msg})
            if assistant_msg:
                messages.append({"role": "assistant", "content": assistant_msg})
    messages.append({"role": "user", "content": user_message})

    try:
        # 2. Tool-calling loop, capped at MAX_TOOL_ROUNDS to prevent runaways.
        for _ in range(MAX_TOOL_ROUNDS):
            response = _create_completion(
                model=LLM_MODEL,
                messages=messages,
                tools=TOOL_DEFINITIONS,
                tool_choice="auto",
            )
            assistant_message = response.choices[0].message

            # Termination (a): no tool calls means the LLM has a final answer.
            if not assistant_message.tool_calls:
                return assistant_message.content or FALLBACK

            # Append the assistant message BEFORE any tool results — the API
            # requires each tool result to follow the call that requested it.
            messages.append(assistant_message)

            # Execute every requested tool call and append its result.
            for tool_call in assistant_message.tool_calls:
                tool_name = tool_call.function.name
                # The model may send "", "null", or malformed JSON for a tool
                # with no required args. Normalize anything that isn't a dict
                # to {} so dispatch_tool always gets a usable mapping.
                raw_args = tool_call.function.arguments
                try:
                    parsed = json.loads(raw_args) if raw_args else {}
                except json.JSONDecodeError:
                    parsed = {}
                tool_args = parsed if isinstance(parsed, dict) else {}
                tool_result = dispatch_tool(tool_name, tool_args)
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": tool_result,
                })

        # Termination (b): hit MAX_TOOL_ROUNDS and still being asked for tools.
        # Force a plain-text answer with one final tool-less call.
        final = _create_completion(
            model=LLM_MODEL,
            messages=messages,
        )
        return final.choices[0].message.content or FALLBACK

    except Exception as e:
        print(f"  [agent error] {e}")
        return FALLBACK
