"""Core substrate behavior — the contracts the benchmarks measured."""

from ada.memory.thought_space import ThoughtSpace


def make_space() -> ThoughtSpace:
    s = ThoughtSpace()
    s.tell_raw(facts={"entity": {"name": "Kara", "kind": "person"},
                      "perceptual": {"color": "blue"}})
    s.tell_raw(facts={"entity": {"name": "Vito", "kind": "person"},
                      "perceptual": {"color": "blue"},
                      "spatial": {"location": "Austin"}})
    s.tell_raw(facts={"entity": {"name": "Vito", "kind": "person"},
                      "relational": {"subject": "Vito", "predicate": "works_as",
                                     "object": "engineer"}})
    s.tell_raw(facts={"entity": {"name": "Mira", "kind": "person"},
                      "perceptual": {"color": "red"},
                      "spatial": {"location": "Austin"}})
    return s


def test_count_where_exact():
    assert make_space().count_where("perceptual", "color", "blue") == 2


def test_distribution():
    assert make_space().distribution("spatial", "location", 5) == [("austin", 2)]


def test_find_where_empty_is_structural_refusal():
    assert make_space().find_where({"perceptual.color": "green"}) == []


def test_entity_join_across_facts():
    # color and job live in DIFFERENT fact records for Vito
    s = make_space()
    assert s.entities_where({"perceptual.color": "blue",
                             "relational.object": "engineer"}) == ["vito"]


def test_entity_join_multi_value_same_slot():
    s = make_space()
    s.tell_raw(facts={"entity": {"name": "Vito"},
                      "relational": {"subject": "Vito", "predicate": "enjoys",
                                     "object": "chess"}})
    assert s.entities_where(
        {"relational.object": ["engineer", "chess"]}) == ["vito"]


def test_predicate_matches_by_containment():
    s = make_space()
    assert s.entities_where({"relational.object": "engineer",
                             "relational.predicate": "work"}) == ["vito"]


def test_versioning_current_belief():
    s = ThoughtSpace()
    s.tell_raw(facts={"entity": {"name": "Carol"},
                      "spatial": {"location": "Austin"}}, key="carol.loc")
    s.tell_raw(facts={"entity": {"name": "Carol"},
                      "spatial": {"location": "Denver"}}, key="carol.loc")
    # current belief: Denver only; history keeps both
    assert s.count_where("spatial", "location", "Austin") == 0
    assert s.count_where("spatial", "location", "Denver") == 1
    chain = s.history("carol.loc")
    assert [t.metadata["_version"] for t in chain] == [1, 2]


def test_recall_superseded_versions_hidden():
    s = ThoughtSpace()
    s.absorb("The hull design is single.", key="hull")
    s.absorb("The hull design is trimaran.", key="hull")
    results = s.recall("what is the hull design?")
    assert results and "trimaran" in results[0].thought.content


def test_recall_questions_never_ground():
    s = ThoughtSpace()
    s.absorb("who are my children?")          # a stored question
    s.absorb("brandi has two children")
    results = s.recall("children brandi")
    assert all(not r.thought.content.endswith("?") for r in results)


def test_recall_excludes_speakers():
    s = ThoughtSpace()
    s.absorb("My name is Ada.", speaker="ada")
    s.absorb("my name is chris", speaker="incoming")
    results = s.recall("what is my name", exclude_speakers=("ada",))
    assert results and "chris" in results[0].thought.content


def test_dedup():
    s = ThoughtSpace()
    assert s.absorb("a fact about dedup") is not None
    assert s.absorb("a fact about dedup") is None


def test_malformed_layers_dropped():
    s = ThoughtSpace()
    stored = s.tell_raw(facts={"entity": [{"name": "broken"}],
                               "perceptual": {"color": "blue"}})
    assert stored is not None
    assert "entity" not in stored.universal
    assert stored.universal["perceptual"]["color"] == "blue"
