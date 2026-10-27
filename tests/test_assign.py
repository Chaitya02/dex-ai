import json
from fractions import Fraction
from types import SimpleNamespace as NS

import pytest
from fastapi.testclient import TestClient

from dex_ai import assign, llm
from dex_ai.app import app
from tests.test_split import LUIGIS

client = TestClient(app)


def call(_tool, _id="c", **args):
    return NS(id=_id, function=NS(name=_tool, arguments=json.dumps(args)))


def reply(tool_calls=None, content=""):
    return NS(choices=[NS(message=NS(tool_calls=tool_calls, content=content))])


class FakeModel:
    """Plays back scripted responses and records what it was sent."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.sent = []
        self.chat = NS(completions=NS(create=self.create))

    def create(self, **kwargs):
        self.sent.append(json.loads(json.dumps(kwargs["messages"])))
        return self.responses.pop(0)


@pytest.fixture
def model(monkeypatch):
    def install(*responses):
        fake = FakeModel(*responses)
        monkeypatch.setattr(llm, "client", lambda config: fake)
        return fake
    monkeypatch.setenv("MODEL_API_KEY", "test")
    return install


def state(**kw):
    return assign.new_state(LUIGIS, ["Aayush", "Ketan", "Kunal"], **kw)


# ---- apply: the tools, validated ----

def test_assign_resolves_me_everyone_and_case():
    s = state()
    assign.apply(s, "assign_item", {"item_id": 1, "people": ["aayush", "KETAN"]})
    assign.apply(s, "assign_item", {"item_id": 2, "people": ["I"]})
    assign.apply(s, "assign_item", {"item_id": 4, "people": ["everyone"]})
    assert list(s.assignments[1]) == ["Aayush", "Ketan"]
    assert list(s.assignments[2]) == ["me"]
    assert list(s.assignments[4]) == ["me", "Aayush", "Ketan", "Kunal"]


def test_assign_weights():
    s = state()
    assign.apply(s, "assign_item", {"item_id": 5, "weights": {"me": 2, "Kunal": 1}})
    assert s.assignments[5] == {"me": Fraction(2), "Kunal": Fraction(1)}


@pytest.mark.parametrize("args, message", [
    ({"item_id": 9, "people": ["me"]}, "No item 9"),
    ({"item_id": 1, "people": ["Sousheel"]}, "isn't in the split"),
    ({"item_id": 1}, "Pass `people` or `weights`"),
    ({"item_id": 1, "weights": {"me": 0}}, "positive"),
])
def test_bad_assign_calls_raise_tool_errors(args, message):
    with pytest.raises(assign.ToolError, match=message):
        assign.apply(state(), "assign_item", args)


def test_add_person_then_assign():
    s = state()
    assert assign.apply(s, "add_person", {"name": "Sousheel"}) == "Added Sousheel"
    assign.apply(s, "assign_item", {"item_id": 6, "people": ["Sousheel"]})
    assert s.added == ["Sousheel"] and "Sousheel" in s.people
    assert "already" in assign.apply(s, "add_person", {"name": "sousheel"})


def test_payer_tax_tip_and_questions():
    s = state()
    assign.apply(s, "set_payer", {"name": "kunal"})
    assign.apply(s, "set_tax_tip", {"mode": "equal"})
    assign.apply(s, "ask_user", {"question": "Who had the tiramisu?"})
    assert (s.payer, s.tax_tip, s.questions) == ("Kunal", "equal", ["Who had the tiramisu?"])


def test_new_state_keeps_existing_assignments_for_corrections():
    s = state(assignments=[{"item_id": 4, "people": ["me", "Aayush"]}], payer="Kunal")
    assert list(s.assignments[4]) == ["me", "Aayush"]
    assert "4. Garlic Knots (qty 2, $9.00): me, Aayush" in s.describe()
    assert "Paid by: Kunal" in s.describe()


# ---- run: the loop ----

def test_run_applies_parallel_calls_and_returns_summary(model):
    fake = model(
        reply([
            call("assign_item", "a", item_id=2, people=["me"]),
            call("assign_item", "b", item_id=1, people=["Aayush", "Ketan"]),
            call("set_payer", "c", name="me"),
        ]),
        reply(content="Assigned the pasta and pizza; you paid."),
    )
    out = assign.run(state(), "I had the pasta, Aayush and Ketan split the pizza, I paid")
    assert out["assignments"] == [
        {"item_id": 1, "weights": {"Aayush": 1.0, "Ketan": 1.0}},
        {"item_id": 2, "weights": {"me": 1.0}},
    ]
    assert out["summary"].startswith("Assigned") and out["steps"] == 2
    # Tool results went back to the model with matching ids.
    tool_msgs = [m for m in fake.sent[1] if m["role"] == "tool"]
    assert [m["tool_call_id"] for m in tool_msgs] == ["a", "b", "c"]


def test_run_feeds_errors_back_so_model_can_fix_them(model):
    fake = model(
        reply([call("assign_item", "a", item_id=1, people=["Sousheel"])]),
        reply([call("add_person", "b", name="Sousheel"),
               call("assign_item", "c", item_id=1, people=["Sousheel"])]),
        reply(content="Sousheel had the pizza."),
    )
    out = assign.run(state(), "Sousheel had the pizza")
    error = next(m for m in fake.sent[1] if m["role"] == "tool")
    assert error["content"].startswith("Error:") and "add_person" in error["content"]
    assert out["added_people"] == ["Sousheel"]
    assert out["assignments"] == [{"item_id": 1, "weights": {"Sousheel": 1.0}}]


def test_run_stops_after_max_steps(model):
    looping = [reply([call("ask_user", str(i), question="?")]) for i in range(assign.MAX_STEPS)]
    model(*looping)
    out = assign.run(state(), "hmm")
    assert out["steps"] == assign.MAX_STEPS and out["summary"] == ""


def test_assign_endpoint(model):
    model(reply([call("assign_item", "a", item_id=3, people=["Kunal"])]), reply(content="ok"))
    resp = client.post("/api/assign", json={
        "receipt": LUIGIS, "transcript": "Kunal had the chicken parm",
        "people": ["Aayush", "Ketan", "Kunal"],
    })
    assert resp.status_code == 200
    assert resp.json()["assignments"] == [{"item_id": 3, "weights": {"Kunal": 1.0}}]


def test_assign_endpoint_needs_a_transcript():
    resp = client.post("/api/assign", json={"receipt": LUIGIS, "transcript": "  ", "people": []})
    assert resp.status_code == 400
