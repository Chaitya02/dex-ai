"""The assignment agent: what someone said -> who had which item.

Muse Spark reads the transcript next to the receipt's numbered items and the
people splitting, and acts only through tools: assign an item, clear one, add
a person, set who paid, set how tax and tip are shared, or ask the user. It
never does arithmetic; split.py does that once the assignments are settled.

Every tool call is validated here before it touches the state. A bad call
(an item number that isn't on the receipt, a name nobody mentioned) goes back
to the model as an error it can correct, never into the split. The same loop
handles corrections: the current assignments go in with the new transcript,
and the model changes only what the user asked to change.
"""
import json
from dataclasses import dataclass, field
from fractions import Fraction

from dex_ai import llm

ME = "me"
MAX_STEPS = 6
SELF_WORDS = {"me", "i", "myself", "mine", "my"}

SYSTEM = """You turn what the user said about a shared bill into item assignments, using tools.

The user is the speaker: "I", "me", "my" mean the person named "me".
"Everyone", "all of us", "we all", "the table" mean every person currently in the split; pass "everyone".

Rules:
- Use the item numbers from the receipt. Match spoken item names loosely ("the pasta" = "Penne alla Vodka", "knots" = "Garlic Knots").
- Several people sharing an item equally: one assign_item call listing them all.
- Unequal shares ("I had two of the three sodas, Kunal had one"): pass weights instead of people.
- A person not yet in the split: call add_person first, then assign.
- "I paid" / "Kunal paid": set_payer. "Split the tip evenly": set_tax_tip.
- Corrections ("no, Aayush didn't have fries"): change only the items mentioned, keeping everyone else on them.
- Never guess. If an item or person is genuinely ambiguous, leave it and call ask_user with one short question.
- Items nobody mentioned stay unassigned. Do not invent assignments.
- Make all the calls you need in one turn when you can. When done, reply with one short sentence summarizing what changed."""

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "assign_item",
            "description": "Set who had one receipt item, replacing any previous assignment of that item. Use `people` for an equal split or `weights` for unequal shares.",
            "parameters": {
                "type": "object",
                "properties": {
                    "item_id": {"type": "integer", "description": "Item number from the receipt"},
                    "people": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Names sharing the item equally. 'me' for the user, 'everyone' for all people in the split.",
                    },
                    "weights": {
                        "type": "object",
                        "additionalProperties": {"type": "number"},
                        "description": "Unequal shares, name -> portion, e.g. {\"me\": 2, \"Kunal\": 1}",
                    },
                },
                "required": ["item_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "unassign_item",
            "description": "Clear an item's assignment entirely.",
            "parameters": {
                "type": "object",
                "properties": {"item_id": {"type": "integer"}},
                "required": ["item_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_person",
            "description": "Add someone the user mentioned who isn't in the split yet.",
            "parameters": {
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_payer",
            "description": "Set who paid the bill.",
            "parameters": {
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_tax_tip",
            "description": "How tax, tip and fees are shared: 'proportional' to what each person had, or 'equal'.",
            "parameters": {
                "type": "object",
                "properties": {"mode": {"type": "string", "enum": ["proportional", "equal"]}},
                "required": ["mode"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ask_user",
            "description": "Ask one short clarifying question when something is genuinely ambiguous.",
            "parameters": {
                "type": "object",
                "properties": {"question": {"type": "string"}},
                "required": ["question"],
            },
        },
    },
]


class ToolError(Exception):
    """A tool call the model can correct; the message goes back to it."""


@dataclass
class State:
    items: dict[int, dict]                               # id -> receipt item
    people: list[str]
    assignments: dict[int, dict[str, Fraction]] = field(default_factory=dict)
    payer: str = ME
    tax_tip: str = "proportional"
    added: list[str] = field(default_factory=list)       # people the agent added
    questions: list[str] = field(default_factory=list)
    actions: list[dict] = field(default_factory=list)    # applied calls, for the UI

    def resolve(self, name: str) -> str:
        """Spoken name -> canonical person, or ToolError listing who exists."""
        key = name.strip().lower()
        if key in SELF_WORDS:
            return ME
        for p in self.people:
            if p.lower() == key:
                return p
        raise ToolError(
            f"{name!r} isn't in the split. People: {', '.join(self.people)}. "
            "Call add_person first if they're new."
        )

    def item(self, item_id) -> dict:
        try:
            return self.items[int(item_id)]
        except (KeyError, TypeError, ValueError):
            raise ToolError(f"No item {item_id}. Items are numbered {min(self.items)}–{max(self.items)}.")

    def describe(self) -> str:
        lines = ["Receipt items:"]
        for i in self.items.values():
            who = self.assignments.get(i["id"])
            had = ", ".join(_fmt_share(n, w, who) for n, w in who.items()) if who else "unassigned"
            lines.append(f"  {i['id']}. {i['name']} (qty {i['quantity']}, ${i['amount_cents'] / 100:.2f}): {had}")
        lines.append(f"People in the split: {', '.join(self.people)}")
        lines.append(f"Paid by: {self.payer}. Tax and tip: {self.tax_tip}.")
        return "\n".join(lines)


def _fmt_share(name, weight, who):
    return name if len(set(who.values())) == 1 else f"{name} ×{weight}"


def apply(state: State, name: str, args: dict) -> str:
    """Run one tool call against the state. Returns a result line for the model."""
    if name == "assign_item":
        item = state.item(args.get("item_id"))
        weights = args.get("weights") or {}
        people = args.get("people") or []
        if not weights and not people:
            raise ToolError("Pass `people` or `weights`.")
        out: dict[str, Fraction] = {}
        for person, w in weights.items():
            try:
                w = Fraction(str(w))
            except ValueError:
                raise ToolError(f"Weight for {person!r} must be a number.")
            if w <= 0:
                raise ToolError("Weights must be positive.")
            out[state.resolve(person)] = w
        for person in people:
            if person.strip().lower() in ("everyone", "all", "everybody"):
                for p in state.people:
                    out.setdefault(p, Fraction(1))
            else:
                out.setdefault(state.resolve(person), Fraction(1))
        state.assignments[item["id"]] = out
        state.actions.append({"tool": name, "item_id": item["id"], "item": item["name"],
                              "people": list(out),
                              "weights": {n: float(w) for n, w in out.items()}})
        return f"Item {item['id']} ({item['name']}) -> {', '.join(out)}"
    if name == "unassign_item":
        item = state.item(args.get("item_id"))
        state.assignments.pop(item["id"], None)
        state.actions.append({"tool": name, "item_id": item["id"], "item": item["name"]})
        return f"Item {item['id']} ({item['name']}) cleared"
    if name == "add_person":
        person = (args.get("name") or "").strip()
        if not person:
            raise ToolError("Name can't be empty.")
        if person.lower() in SELF_WORDS:
            return "That's the user ('me'), already in the split."
        for p in state.people:
            if p.lower() == person.lower():
                return f"{p} is already in the split."
        state.people.append(person)
        state.added.append(person)
        state.actions.append({"tool": name, "name": person})
        return f"Added {person}"
    if name == "set_payer":
        state.payer = state.resolve(args.get("name") or "")
        state.actions.append({"tool": name, "name": state.payer})
        return f"Paid by {state.payer}"
    if name == "set_tax_tip":
        mode = args.get("mode")
        if mode not in ("proportional", "equal"):
            raise ToolError("mode must be 'proportional' or 'equal'.")
        state.tax_tip = mode
        state.actions.append({"tool": name, "mode": mode})
        return f"Tax and tip: {mode}"
    if name == "ask_user":
        question = (args.get("question") or "").strip()
        if question:
            state.questions.append(question)
        return "Question noted; carry on with everything else."
    raise ToolError(f"Unknown tool {name!r}.")


def run(state: State, transcript: str, config: llm.LLMConfig | None = None) -> dict:
    """Let the model act on `transcript` through tools until it stops."""
    config = config or llm.config_from_env()
    client = llm.client(config)
    messages = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": f"{state.describe()}\n\nThe user said:\n\"{transcript.strip()}\""},
    ]
    summary, steps = "", 0
    for steps in range(1, MAX_STEPS + 1):
        response = client.chat.completions.create(
            model=config.model, messages=messages, tools=TOOLS, temperature=0,
        )
        msg = response.choices[0].message
        if not msg.tool_calls:
            summary = (msg.content or "").strip()
            break
        messages.append({
            "role": "assistant",
            "content": msg.content or "",
            "tool_calls": [
                {"id": c.id, "type": "function",
                 "function": {"name": c.function.name, "arguments": c.function.arguments}}
                for c in msg.tool_calls
            ],
        })
        for call in msg.tool_calls:
            try:
                args = json.loads(call.function.arguments or "{}")
                result = apply(state, call.function.name, args)
            except json.JSONDecodeError:
                result = "Error: arguments weren't valid JSON."
            except ToolError as e:
                result = f"Error: {e}"
            messages.append({"role": "tool", "tool_call_id": call.id, "content": result})
    return {
        "assignments": [
            {"item_id": i, "weights": {n: float(w) for n, w in who.items()}}
            for i, who in sorted(state.assignments.items())
        ],
        "people": state.people,
        "added_people": state.added,
        "payer": state.payer,
        "tax_tip": state.tax_tip,
        "questions": state.questions,
        "actions": state.actions,
        "summary": summary,
        "steps": steps,
    }


def new_state(receipt: dict, people: list[str], assignments: list[dict] | None = None,
              payer: str = ME, tax_tip: str = "proportional") -> State:
    """Build the agent's state from a normalized receipt and the current split."""
    names: list[str] = [ME]
    for p in people:
        p = p.strip()
        if p and p.lower() not in SELF_WORDS and p.lower() not in (n.lower() for n in names):
            names.append(p)
    state = State(items={i["id"]: i for i in receipt["items"]}, people=names,
                  payer=payer or ME, tax_tip=tax_tip)
    for a in assignments or []:
        weights = a.get("weights") or {n: 1 for n in a.get("people", [])}
        resolved = {}
        for n, w in weights.items():
            try:
                resolved[state.resolve(n)] = Fraction(str(w))
            except ToolError:
                state.people.append(n)
                resolved[n] = Fraction(str(w))
        if resolved and a["item_id"] in state.items:
            state.assignments[a["item_id"]] = resolved
    return state
