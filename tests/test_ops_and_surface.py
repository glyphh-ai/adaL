"""The closed op set and the ask surface (offline — no LLM)."""

import pytest

from ada.cognitive.ops import execute_op
from ada.cognitive.surface import CognitiveSurface
from ada.memory.thought_space import ThoughtSpace


@pytest.fixture()
def space() -> ThoughtSpace:
    s = ThoughtSpace()
    for name, city, job in (("Ann", "Boston", "doctor"),
                            ("Bo", "Boston", "engineer"),
                            ("Cy", "Denver", "engineer")):
        s.tell_raw(facts={"entity": {"name": name, "kind": "person"},
                          "spatial": {"location": city}})
        s.tell_raw(facts={"entity": {"name": name, "kind": "person"},
                          "relational": {"subject": name,
                                         "predicate": "works_as",
                                         "object": job}})
    return s


def test_op_count(space):
    assert execute_op(space, {"op": "count",
                              "conditions": {"spatial.location": "boston"}}) == "2"


def test_op_who_intersection(space):
    out = execute_op(space, {"op": "who", "conditions": {
        "spatial.location": "boston", "relational.object": "engineer"}})
    assert out == "bo"


def test_op_top_with_predicate_filter(space):
    out = execute_op(space, {"op": "top", "slot": "relational.object",
                             "predicate_contains": "work"})
    assert out.startswith("engineer (2)")


def test_op_compare(space):
    out = execute_op(space, {"op": "compare", "slot": "spatial.location",
                             "a": "boston", "b": "denver"})
    assert out.startswith("boston")


def test_op_refuse_and_unknown(space):
    assert execute_op(space, {"op": "refuse"}) == "I don't know."
    with pytest.raises(ValueError):
        execute_op(space, {"op": "drop_tables"})


def test_ask_refuses_unknowable(space):
    a = CognitiveSurface(space).ask("what is ann's salary?")
    assert a.refused


def test_ask_two_hop_widens_view():
    s = ThoughtSpace()
    s.absorb("my wifes name is brandi")
    s.absorb("brandi has two children named traceton and carson")
    surface = CognitiveSurface(s)
    a = surface.ask("who is my wife?")
    assert not a.refused and "brandi" in a.fact.content
