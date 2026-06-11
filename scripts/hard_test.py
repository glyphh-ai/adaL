"""
HARD TEST — proving 'Claude with Ada wired in' actually works as a memory.

Simulates a long-running cross-session relationship between Claude (the
renderer) and Ada (the substrate). The setup is a fictional research
project ("Project Aurora" — a self-driving boat) where 80 facts accumulate
over many "sessions," including versioned decisions that change over time
and contradictions that need to be resolved by recency.

Then we run 25 queries categorised by difficulty:

  A. Direct recall          (5)  — basic surface
  B. Multi-hop inference    (5)  — must join ≥2 facts
  C. Version-aware recall   (5)  — current value, or what changed
  D. Schema introspection   (3)  — Ada describing herself
  E. Absence detection      (3)  — did we discuss X? (correct answer = no)
  F. Long-horizon synthesis (4)  — need many facts to answer

If the architecture (substrate + LLM-at-build-time enrichment + versioning
+ schema tracker + LLM renderer) actually solves the memory problem, the
score across all six categories should be > 75% — substantially better
than what a context-window-limited LLM could do on the same task.

    ANTHROPIC_API_KEY=... PYTHONPATH=. python scripts/hard_test.py
"""

from __future__ import annotations

import time

from ada.cognitive.generate import build_llm_renderer
from ada.cognitive.surface import CognitiveSurface
from ada.encoder.llm_enricher import auto_enricher
from ada.memory.thought_space import ThoughtSpace
from ada.skill import SchemaTracker


# ── Session 1 — accumulated facts about Project Aurora ──────────────
#
# Format: (text, key_or_None). When key is provided, this absorb is
# treated as a version in that key's chain — same key, later version,
# delta computed by TemporalEncoder.

SESSION_1: list[tuple[str, str | None]] = [
    # — Team —
    ("Chris is the lead engineer of Project Aurora.", "aurora.lead"),
    ("Brandi is the project manager of Project Aurora.", "aurora.pm"),
    ("Jim is the navigation specialist on Project Aurora.", "aurora.navigation"),
    ("Bob is the hull designer on Project Aurora.", "aurora.hull_designer"),
    ("Kira joined Project Aurora as the sensor engineer.", "aurora.sensors"),
    ("Lex is the propulsion lead on Project Aurora.", "aurora.propulsion"),

    # — Scope and goals —
    ("Project Aurora is building a self-driving boat.", None),
    ("Project Aurora targets the recreational sailing market.", "aurora.market"),
    ("The Aurora boat is 32 feet long.", "aurora.boat_length"),
    ("Aurora's top speed target is 25 knots.", "aurora.top_speed"),

    # — Design decisions, with versioning —
    ("The Aurora boat uses a single hull design.", "aurora.hull"),
    ("The Aurora boat uses a catamaran hull design.", "aurora.hull"),         # v2
    ("The Aurora boat uses a trimaran hull design.", "aurora.hull"),          # v3 — final

    ("Aurora's primary sensor is LIDAR.", "aurora.primary_sensor"),
    ("Aurora's primary sensor is stereo cameras.", "aurora.primary_sensor"),  # v2 (final)

    ("Aurora uses gasoline propulsion.", "aurora.propulsion_type"),
    ("Aurora uses electric propulsion.", "aurora.propulsion_type"),          # v2 (final)

    # — Timeline, with versioning —
    ("Aurora's first prototype is scheduled for March 2026.", "aurora.prototype_date"),
    ("Aurora's first prototype is scheduled for June 2026.", "aurora.prototype_date"),  # v2

    ("Aurora's commercial launch is scheduled for 2027.", "aurora.launch_date"),
    ("Aurora's commercial launch is scheduled for 2028.", "aurora.launch_date"),  # v2

    # — Constraints —
    ("Aurora must operate in waves up to 4 feet tall.", "aurora.wave_spec"),
    ("Aurora must remain under 250 kilograms total weight.", "aurora.weight"),
    ("Aurora's battery must last at least 6 hours.", "aurora.battery_endurance"),
    ("Aurora's onboard computer must be Raspberry Pi 5.", "aurora.compute"),

    # — Budget —
    ("Project Aurora has a budget of 200,000 dollars.", "aurora.budget"),
    ("Project Aurora's budget was increased to 350,000 dollars.", "aurora.budget"),  # v2

    # — Testing locations —
    ("Aurora will be tested at Lake Travis in Austin.", "aurora.test_location"),
    ("Aurora's first sea trial will happen at Galveston Bay.", "aurora.sea_trial_location"),

    # — Investor decisions —
    ("The Aurora seed round closed at 500,000 dollars.", "aurora.seed_round"),
    ("Andreessen Horowitz led the Aurora seed round.", "aurora.lead_investor"),
    ("Y Combinator participated in the Aurora seed round.", "aurora.yc_participation"),

    # — Patents —
    ("Project Aurora filed a patent on its stereo-vision waypoint algorithm.", "aurora.patent.vision"),
    ("Project Aurora filed a patent on its low-power compute architecture.", "aurora.patent.compute"),

    # — Code / infrastructure —
    ("Aurora's codebase is hosted on GitHub at aurora-marine/aurora.", "aurora.repo"),
    ("Aurora's backend runs on AWS in us-east-1.", "aurora.cloud_region"),
    ("Aurora uses PostgreSQL for telemetry storage.", "aurora.database"),
    ("Aurora uses Kafka for real-time event streaming.", "aurora.messaging"),

    # — Partnerships —
    ("Project Aurora partnered with Garmin for marine GPS modules.", "aurora.partner.gps"),
    ("Project Aurora partnered with Sony for image sensors.", "aurora.partner.imaging"),

    # — Outcomes & milestones —
    ("Aurora completed its first basin test in November 2025.", "aurora.milestone.basin"),
    ("Aurora passed Coast Guard preliminary certification in February 2026.", "aurora.milestone.cert"),
    ("Aurora's CES 2026 demo received 12 press mentions.", "aurora.ces_mentions"),
    ("Aurora's beta program will have 50 boats in the first wave.", "aurora.beta_size"),

    # — Discontinued ideas —
    ("Project Aurora considered a foiling hull design but rejected it for cost.", None),
    ("Project Aurora considered diesel propulsion but rejected it for emissions.", None),

    # — Personal facts about the user (Chris) accumulated over sessions —
    ("Chris's favorite color is blue.", "chris.favorite_color"),
    ("Chris lives in Austin, Texas.", "chris.location"),
    ("Chris previously worked at Boomi.", "chris.history.boomi"),
    ("Chris uses a Mac for development.", "chris.dev_machine"),
    ("Chris prefers TypeScript over Python for new projects.", "chris.lang_preference"),
    ("Chris's daughter is named Jin.", "chris.daughter"),
    ("Chris drinks coffee, not tea.", "chris.beverage"),

    # — Filler / red-herring facts (to make recall harder) —
    ("The Mediterranean Sea has an average depth of 1,500 meters.", None),
    ("The Pacific Ocean covers about 30 percent of Earth's surface.", None),
    ("Sailing was a primary form of transport before the steam engine.", None),
    ("The America's Cup is the oldest international sporting trophy.", None),
    ("Most marine batteries are lithium iron phosphate.", None),
    ("Marine LIDAR has shorter range than automotive LIDAR.", None),
    ("Stereo vision computes depth from two parallel cameras.", None),
    ("Galvanized hardware resists saltwater corrosion.", None),
    ("Marina slip fees in Austin average 12 dollars per foot per month.", None),
    ("Sun glare is a known challenge for marine vision systems.", None),
    ("ARM-based computers are common for robotics due to low power.", None),
    ("Kafka was open-sourced by LinkedIn in 2011.", None),
    ("Garmin was founded in 1989 and is based in Kansas.", None),
    ("Sony's IMX sensors power the iPhone camera lineup.", None),
    ("Y Combinator's accelerator program runs twice per year.", None),
    ("Andreessen Horowitz manages over 35 billion dollars in assets.", None),
    ("Project Apollo was the first program to land humans on the Moon.", None),
    ("Project Mercury was NASA's first human spaceflight program.", None),
    ("The Manhattan Project built the first atomic bombs.", None),
    ("Most patent applications are confidential for 18 months.", None),
    ("Coast Guard certification requires hull stability testing.", None),
    ("CES is held annually in Las Vegas in January.", None),
    ("AWS us-east-1 is the largest commercial cloud region.", None),
    ("Marina La Crosse is the largest freshwater marina in the US.", None),
]
assert len(SESSION_1) == 77, f"expected 77 facts, got {len(SESSION_1)}"


# ── 25 hard queries with category + expected substring ───────────────

QUERIES: list[tuple[str, str, str, str]] = [
    # category, query, expected substring (any case)
    # A. Direct recall (5)
    ("A", "Who is the lead engineer of Project Aurora?",                  "Chris",                      ""),
    ("A", "How long is the Aurora boat?",                                  "32",                         ""),
    ("A", "Where is Aurora's codebase hosted?",                            "github",                     "aurora-marine/aurora"),
    ("A", "What is Aurora's top speed target?",                            "25",                         "knots"),
    ("A", "Who is Chris's daughter?",                                      "Jin",                        ""),

    # B. Multi-hop inference (5)
    ("B", "Who works on hardware design for Aurora?",                      "Bob",                        ""),  # hull designer
    ("B", "What does the sensor engineer on Aurora do?",                   "Kira",                       ""),
    ("B", "Is Aurora a marine project or aerospace project?",              "marine",                     ""),  # boat → marine
    ("B", "What kind of beverage would Chris likely order at a meeting?",  "coffee",                     ""),
    ("B", "Could Aurora's compute platform handle heavy GPU workloads?",   "Raspberry Pi",               ""),  # implication: no

    # C. Version-aware recall (5) — should return LATEST version
    ("C", "What hull design does Aurora currently use?",                   "trimaran",                   ""),
    ("C", "What is Aurora's current primary sensor?",                      "stereo cameras",             ""),
    ("C", "What kind of propulsion does Aurora use?",                      "electric",                   ""),
    ("C", "When is Aurora's first prototype scheduled?",                   "June",                       "2026"),
    ("C", "What is Aurora's current budget?",                              "350,000",                    ""),

    # D. Schema introspection (3)
    ("D", "What topics does Ada know about?",                              "aurora",                     ""),
    ("D", "What predicates exist for Aurora?",                             "hull",                       ""),
    ("D", "What kinds of decisions has the Aurora team made?",             "design",                     ""),

    # E. Absence detection (3) — correct answer = "I don't know" / "no information"
    ("E", "What is the color of Aurora's interior fabric?",                "don't know",                 "no information"),
    ("E", "Who is Aurora's CTO?",                                          "don't know",                 "no information"),
    ("E", "What is Bob's salary?",                                         "don't know",                 "no information"),

    # F. Long-horizon synthesis (4)
    ("F", "Summarize Aurora's investor situation.",                        "Andreessen Horowitz",        "Y Combinator"),
    ("F", "What design decisions has the Aurora team changed?",            "hull",                       ""),
    ("F", "What partnerships has Aurora secured?",                         "Garmin",                     "Sony"),
    ("F", "What testing milestones has Aurora achieved?",                  "basin",                      ""),
]
assert len(QUERIES) == 25, f"expected 25 queries, got {len(QUERIES)}"


# ── runner ──────────────────────────────────────────────────────────

def main() -> None:
    enricher = auto_enricher()
    space = ThoughtSpace(enricher=enricher)
    tracker = SchemaTracker(space, history_path="docs/aurora_schema.md")
    renderer = build_llm_renderer()
    surface = CognitiveSurface(space, renderer=renderer)

    # ── SESSION 1: ingest 80 facts with versioning ──
    print("─── SESSION 1: ingesting 80 facts about Project Aurora ───\n")
    t0 = time.time()
    for text, key in SESSION_1:
        stored = space.absorb(text, key=key)
        if stored:
            tracker.observe(stored)
    print(f"  ingested in {time.time() - t0:.1f}s. "
          f"Substrate holds {space.count} thoughts.\n")
    summ = tracker.summary()
    print(f"  schema: {summ['predicates_known']} predicates, "
          f"{summ['topics_known']} topics learned.")
    print(f"  versioned keys: {sum(1 for v in space._history_by_key.values() if len(v) > 1)} "
          f"have multiple versions.\n")

    # ── SESSION 2: hard queries ──
    print("─── SESSION 2: 25 hard queries (fresh evaluation pass) ───\n")
    # Phrases that count as a correct "I don't know" for absence (E) queries.
    REFUSAL_PHRASES = (
        "don't know", "do not know", "no information",
        "do not contain", "doesn't contain", "doesn't include",
        "cannot answer", "can't answer", "not in the memories",
        "memories don't", "memories do not",
    )

    by_cat: dict[str, list[bool]] = {c: [] for c in "ABCDEF"}
    rows = []
    t0 = time.time()
    for i, (cat, q, want_a, want_b) in enumerate(QUERIES, 1):
        # Synthesis queries need more facts surfaced for the renderer.
        top_k = 12 if cat == "F" else 5
        answer = surface.ask(q, top_chains=top_k)
        ans = (answer.rendered or "").lower()
        if cat == "E":
            ok = any(p in ans for p in REFUSAL_PHRASES)
        else:
            ok = bool(want_a) and want_a.lower() in ans
            if not ok and want_b:
                ok = want_b.lower() in ans
        by_cat[cat].append(ok)
        rows.append((cat, q, ans, ok))
        mark = "✓" if ok else "✗"
        print(f"  [{cat}{i:>2}] {mark}  {q[:55]}")
    print(f"\n  ran 25 queries in {time.time() - t0:.1f}s\n")

    # ── results ──
    print("─" * 96)
    print(f"{'CAT':<4}{'#':<4}{'QUERY':<50}{'RESPONSE':<30}{'OK':<3}")
    print("─" * 96)
    for i, (cat, q, ans, ok) in enumerate(rows, 1):
        mark = "✓" if ok else "✗"
        print(f"{cat:<4}{i:<4}{q[:48]:<50}{ans[:28]:<30}{mark:<3}")
    print("─" * 96)

    print()
    print("─── Category breakdown ───")
    names = {
        "A": "Direct recall",
        "B": "Multi-hop inference",
        "C": "Version-aware recall",
        "D": "Schema introspection",
        "E": "Absence detection",
        "F": "Long-horizon synthesis",
    }
    total_ok, total = 0, 0
    for c in "ABCDEF":
        oks = by_cat[c]
        n_ok = sum(oks)
        n = len(oks)
        total_ok += n_ok
        total += n
        pct = 100 * n_ok / n if n else 0
        print(f"   {c}. {names[c]:<25} {n_ok}/{n}  ({pct:>3.0f}%)")
    print()
    print(f"   OVERALL: {total_ok}/{total}  ({100*total_ok/total:.0f}%)")


if __name__ == "__main__":
    main()
