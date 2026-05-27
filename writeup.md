# Finance Agent — One-Page Writeup

---

## 1. Memory: What did you store, and what did you deliberately not store?

**Stored after Session 1:**
- `savings_plan` — monthly house fund target (₹30,000), total goal (₹15 lakh), timeline (24 months), feasibility notes
- `commitments` — explicit things the user agreed to: save ₹30,000 this month, cut food delivery in half
- `reminders_set` — the reminder confirmed by the tool (date + content)
- `food_budget_target` — last month's food delivery spend (₹12,240) and the new target (₹6,120)

**Deliberately not stored:**
- Raw transaction lists — too large, not durable, and tool data should always be fetched fresh
- Account balances — these change; storing them would cause the agent to quote stale numbers in Session 2
- Upcoming bills — same reason; Session 2 correctly fetches fresh bills and sees rent is already paid

**Why:** Memory is for things that don't come from tools — user intent, commitments, and goals. Anything a tool can answer should be answered by calling the tool, not reading memory.

---

## 2. Tools vs LLM: One decision each way

**Given to the LLM — which tools to call and when:**
The agent doesn't hardcode "call balance before every response." The LLM reads the user's message and decides which tools are relevant. In Session 2, it independently called `get_account_balance`, `get_recent_transactions`, and `get_upcoming_bills` before answering the MacBook question — without being told to. This requires judgment, so it belongs to the LLM.

**Kept as code — spend aggregation by category:**
The `summarize_tool_result` function computes total food delivery spend, total debits, and total upcoming bills in plain Python. This is arithmetic on structured data — there's no judgment involved. Doing this in the LLM would be slower, less reliable, and wasteful of tokens.

---

## 3. AI Usage: What was generated, and where did you push back?

**Generated with AI (Codex + Claude):**
- Initial `agent.py` scaffold — tool schemas, agent loop, memory read/write structure
- The `extract_memory` function that converts Session 1 transcript into structured JSON
- The `summarize_tool_result` helper
- Bug fixes for the Groq API message format (tool call serialization, null arguments handling)

**One specific rejection:**
Codex initially suggested passing the full `messages` list (including all tool call/result objects) to `extract_memory`. This was wrong — the messages list contains raw Groq API objects with tool call metadata that the LLM doesn't need to parse, and it would waste tokens sending redundant data. We changed it to pass only the clean `transcript` list (user/assistant text pairs), which is all the memory extractor actually needs.

---

## 4. One Week More: What would you redesign?

**The memory layer — from a flat JSON file to a structured, append-only log.**

Right now, `memory.json` is overwritten after Session 1. If there were a Session 3, the agent has no way to know what changed between sessions — it just sees the latest snapshot.

With another week, I'd redesign memory as an append-only event log: each session adds a timestamped entry with what changed, what was committed, and what tools returned. The system prompt would then summarize the last N entries, giving the agent a sense of history and drift (e.g., "she committed to cutting food delivery in Session 1 but spent ₹3,830 by Session 2 — is she on track?"). This makes the agent genuinely longitudinal rather than just session-aware.
