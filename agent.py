import argparse
import json
import os
from collections import defaultdict
from pathlib import Path

from groq import Groq

from tools import (
    get_account_balance,
    get_recent_transactions,
    get_upcoming_bills,
    set_reminder,
)


MODEL = "llama-3.3-70b-versatile"
MEMORY_FILE = Path("memory.json")

USER_PROFILE = {
    "name": "Priya Sharma",
    "age": 28,
    "city": "Bangalore",
    "monthly_income_inr": 120000,
    "stated_goal": "Save ₹15 lakh in 2 years for a house down payment",
}

SCRIPTED_SESSIONS = {
    "session1": [
        "I just got my salary credited. Help me figure out how much I can realistically save this month.",
        "I feel like I'm spending too much on food delivery. How much did I actually spend on it last month?",
        "Okay that's worse than I thought. Let's say I want to cut that in half AND put aside ₹30,000 for my house fund this month — is that realistic given my upcoming bills?",
        "Got it. Remind me to actually transfer the ₹30,000 to my house fund on the 25th.",
    ],
    "session2": [
        "Hey, my colleague is selling his MacBook for ₹80,000, barely used. I've been wanting to upgrade. Should I buy it?",
    ],
}

TOOLS = {
    "get_recent_transactions": get_recent_transactions,
    "get_account_balance": get_account_balance,
    "get_upcoming_bills": get_upcoming_bills,
    "set_reminder": set_reminder,
}

TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "get_recent_transactions",
            "description": "Return recent transactions. Negative amounts are spending; positive amounts are income.",
            "parameters": {
                "type": "object",
                "properties": {"days": {"type": "integer", "minimum": 1, "maximum": 90}},
                "required": ["days"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_account_balance",
            "description": "Return current account balances in INR.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_upcoming_bills",
            "description": "Return upcoming bills due within the requested number of days.",
            "parameters": {
                "type": "object",
                "properties": {"days": {"type": "integer", "minimum": 1, "maximum": 90}},
                "required": ["days"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_reminder",
            "description": "Set a reminder for the user. Date must be YYYY-MM-DD.",
            "parameters": {
                "type": "object",
                "properties": {
                    "date": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["date", "content"],
            },
        },
    },
]


def log(label, payload):
    print(f"\n[{label}] {json.dumps(payload, ensure_ascii=False, indent=2)}")


def read_memory():
    if not MEMORY_FILE.exists():
        log("MEMORY_READ", {"exists": False, "session": 1})
        return None
    memory = json.loads(MEMORY_FILE.read_text(encoding="utf-8"))
    log("MEMORY_READ", {"exists": True, "session": 2, "memory": memory})
    return memory


def write_memory(memory):
    MEMORY_FILE.write_text(json.dumps(memory, ensure_ascii=False, indent=2), encoding="utf-8")
    log("MEMORY_WRITE", memory)


def summarize_tool_result(name, result):
    if name == "get_recent_transactions":
        by_month_category = defaultdict(int)
        for txn in result:
            if txn["amount"] < 0:
                key = f"{txn['date'][:7]}:{txn['category']}"
                by_month_category[key] += abs(txn["amount"])
        return {
            "raw_result": result,
            "computed_summary": {
                "spend_by_month_category_inr": dict(sorted(by_month_category.items())),
                "total_debits_inr": sum(abs(t["amount"]) for t in result if t["amount"] < 0),
                "total_credits_inr": sum(t["amount"] for t in result if t["amount"] > 0),
            },
        }
    if name == "get_upcoming_bills":
        return {
            "raw_result": result,
            "computed_summary": {"total_upcoming_bills_inr": sum(b["amount"] for b in result)},
        }
    if name == "get_account_balance":
        return {
            "raw_result": result,
            "computed_summary": {
                "total_balance_inr": sum(result.values()),
                "liquid_balance_inr": result.get("checking", 0) + result.get("savings", 0),
            },
        }
    return result


def system_prompt(memory):
    memory_text = json.dumps(memory, ensure_ascii=False, indent=2) if memory else "No prior memory yet."
    rules = [
        "Use tools for current balances, recent transactions, upcoming bills, and reminders.",
        "Prefer computed_summary values from tool results for arithmetic.",
        "Do not invent tool data. If a number depends on balances, bills, or spending, call tools.",
        "Be concise, specific, and judgment-oriented. Mention tradeoffs and next actions.",
        "In Session 2, actively connect new advice to remembered commitments and refresh changed facts with tools.",
    ]
    if memory is not None:
        food_target = memory.get("food_budget_target", {}).get("monthly_target_inr")
        if food_target is not None:
            rules.append(
                "If the user's current food delivery spending this month is close to or exceeding "
                f"their target of {food_target}, flag it proactively alongside any new financial decision."
            )
        rules.append(
            "Proactively check if the user is on track with their food delivery budget commitment "
            "and mention it when relevant to a new spending decision."
        )
    rules_text = "\n".join(f"- {rule}" for rule in rules)
    return f"""
You are a practical finance companion for one user.

User profile:
{json.dumps(USER_PROFILE, ensure_ascii=False, indent=2)}

Existing memory:
{memory_text}

Rules:
{rules_text}
""".strip()


def execute_tool(tool_call):
    name = tool_call.function.name
    raw_args = tool_call.function.arguments
    args = json.loads(raw_args) if raw_args and raw_args != 'null' else {}
    log("TOOL_CALL", {"name": name, "arguments": args})
    result = TOOLS[name](**args)
    log("TOOL_RESULT", {"name": name, "result": result})
    tool_payload = summarize_tool_result(name, result)
    return {
        "role": "tool",
        "tool_call_id": tool_call.id,
        "content": json.dumps(tool_payload, ensure_ascii=False),
    }


"""
def assistant_message_dict(message):
    data = {"role": "assistant", "content": message.content or ""}
    if message.tool_calls:
        data["tool_calls"] = [tc.model_dump() for tc in message.tool_calls]
    return data
"""

def assistant_message_dict(message):
    data = {"role": "assistant", "content": message.content or ""}
    if message.tool_calls:
        data["tool_calls"] = [
            {
                "id": tc.id,
                "type": "function",
                "function": {
                    "name": tc.function.name,
                    "arguments": tc.function.arguments or "{}",
                },
            }
            for tc in message.tool_calls
        ]
    return data

def run_agent_turn(client, messages):
    while True:
        response = client.chat.completions.create(
            model=MODEL,
            messages=messages,
            tools=TOOL_SCHEMAS,
            tool_choice="auto",
            temperature=0.2,
        )
        message = response.choices[0].message
        messages.append(assistant_message_dict(message))
        if not message.tool_calls:
            return message.content or ""
        for tool_call in message.tool_calls:
            messages.append(execute_tool(tool_call))


def extract_memory(client, transcript):
    prompt = """
Extract durable memory from Session 1 only. Return strict JSON with these keys:
- savings_plan: object with monthly_house_fund_target_inr, total_goal_inr, timeline_months, feasibility_notes
- commitments: array of user commitments
- reminders_set: array of reminders/actions confirmed by tools
- food_budget_target: object with previous_month_food_delivery_inr and monthly_target_inr

Store only facts useful for future financial advice. Do not store full transaction lists.
""".strip()
    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": prompt},
            {"role": "user", "content": json.dumps(transcript, ensure_ascii=False)},
        ],
        response_format={"type": "json_object"},
        temperature=0,
    )
    return json.loads(response.choices[0].message.content)


def run_conversation(user_inputs):
    if not os.getenv("GROQ_API_KEY"):
        raise SystemExit("Set GROQ_API_KEY in the environment before running.")

    client = Groq(api_key=os.environ["GROQ_API_KEY"])
    starting_memory = read_memory()
    messages = [{"role": "system", "content": system_prompt(starting_memory)}]
    transcript = []

    for user_text in user_inputs:
        print(f"\nUSER: {user_text}")
        messages.append({"role": "user", "content": user_text})
        answer = run_agent_turn(client, messages)
        print(f"\nASSISTANT: {answer}")
        transcript.append({"user": user_text, "assistant": answer})

    if starting_memory is None:
        memory = extract_memory(client, messages)
        write_memory(memory)


def interactive_inputs():
    print("Enter user messages. Press Ctrl-D when the session is done.\n")
    while True:
        try:
            text = input("USER: ").strip()
        except EOFError:
            break
        if text:
            yield text


def main():
    parser = argparse.ArgumentParser(description="Tiny Groq finance agent")
    parser.add_argument("--script", choices=SCRIPTED_SESSIONS.keys(), help="Run assignment session messages")
    args = parser.parse_args()
    user_inputs = SCRIPTED_SESSIONS[args.script] if args.script else list(interactive_inputs())
    run_conversation(user_inputs)


if __name__ == "__main__":
    main()
