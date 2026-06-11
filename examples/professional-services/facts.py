"""
Meridian Advisory — a fictional ~40-person consulting firm.

~90 natural-language facts of the kind that accumulate in a real
professional-services practice: engagements, staffing, fee models,
versioned policies, and lessons learned. Facts with a `key` are
versioned — later statements supersede earlier ones, and the full
chain stays queryable.

Everything here is invented; any resemblance to real firms is
coincidental.
"""

# (text, key_or_None) — keys make a fact versioned.
FACTS: list[tuple[str, str | None]] = [
    # ── Engagements ──────────────────────────────────────────────
    ("The Northwind engagement is an ERP migration for a logistics client.", "eng.northwind.type"),
    ("The Northwind engagement is billed fixed-fee.", "eng.northwind.fee"),
    ("Priya Sharma is the lead partner on the Northwind engagement.", "eng.northwind.lead"),
    ("The Northwind engagement is in the logistics industry.", None),

    ("The Atlas engagement is a cost-reduction program for a hospital network.", "eng.atlas.type"),
    ("The Atlas engagement is billed time-and-materials.", "eng.atlas.fee"),
    ("Marcus Webb is the lead partner on the Atlas engagement.", "eng.atlas.lead"),
    ("The Atlas engagement is in the healthcare industry.", None),

    ("The Beacon engagement is a digital strategy review for a retail bank.", "eng.beacon.type"),
    ("The Beacon engagement is billed fixed-fee.", "eng.beacon.fee"),
    ("Priya Sharma is the lead partner on the Beacon engagement.", "eng.beacon.lead"),
    ("The Beacon engagement is in the financial services industry.", None),

    ("The Caldera engagement is a post-merger integration for an energy company.", "eng.caldera.type"),
    ("The Caldera engagement is billed time-and-materials.", "eng.caldera.fee"),
    ("Elena Voss is the lead partner on the Caldera engagement.", "eng.caldera.lead"),
    ("The Caldera engagement is in the energy industry.", None),

    ("The Dunmore engagement is a supply-chain assessment for a food manufacturer.", "eng.dunmore.type"),
    ("The Dunmore engagement is billed fixed-fee.", "eng.dunmore.fee"),
    ("Marcus Webb is the lead partner on the Dunmore engagement.", "eng.dunmore.lead"),
    ("The Dunmore engagement is in the manufacturing industry.", None),

    ("The Egret engagement is a data platform build for a healthcare payer.", "eng.egret.type"),
    ("The Egret engagement is billed fixed-fee.", "eng.egret.fee"),
    ("Elena Voss is the lead partner on the Egret engagement.", "eng.egret.lead"),
    ("The Egret engagement is in the healthcare industry.", None),

    # Engagement status — versioned (status changes over time)
    ("The Northwind engagement is in the discovery phase.", "eng.northwind.status"),
    ("The Northwind engagement has moved to the implementation phase.", "eng.northwind.status"),
    ("The Atlas engagement is in the proposal stage.", "eng.atlas.status"),
    ("The Atlas engagement was signed and is now active.", "eng.atlas.status"),
    ("The Beacon engagement is active.", "eng.beacon.status"),
    ("The Caldera engagement is on hold pending client board approval.", "eng.caldera.status"),
    ("The Dunmore engagement closed in May 2026.", "eng.dunmore.status"),
    ("The Egret engagement is active.", "eng.egret.status"),

    # ── Staff ────────────────────────────────────────────────────
    ("Priya Sharma is a partner specializing in digital transformation.", None),
    ("Priya Sharma is based in the Chicago office.", "staff.priya.office"),
    ("Marcus Webb is a partner specializing in operations.", None),
    ("Marcus Webb is based in the Denver office.", "staff.marcus.office"),
    ("Elena Voss is a partner specializing in M&A integration.", None),
    ("Elena Voss is based in the Boston office.", "staff.elena.office"),
    ("Dan Okafor is a senior manager on the data practice.", None),
    ("Dan Okafor is based in the Chicago office.", "staff.dan.office"),
    ("Dan Okafor moved to the Boston office in April 2026.", "staff.dan.office"),
    ("Sofia Reyes is a manager on the operations practice.", None),
    ("Sofia Reyes is based in the Denver office.", "staff.sofia.office"),
    ("Tom Iverson is a senior consultant on the strategy practice.", None),
    ("Tom Iverson is based in the Boston office.", "staff.tom.office"),

    # Staffing assignments
    ("Dan Okafor is staffed on the Egret engagement.", None),
    ("Sofia Reyes is staffed on the Atlas engagement.", None),
    ("Sofia Reyes is staffed on the Dunmore engagement.", None),
    ("Tom Iverson is staffed on the Beacon engagement.", None),

    # ── Rates — versioned ────────────────────────────────────────
    ("The standard partner billing rate is 650 dollars per hour.", "rates.partner"),
    ("The standard partner billing rate increased to 700 dollars per hour.", "rates.partner"),
    ("The standard manager billing rate is 375 dollars per hour.", "rates.manager"),
    ("The standard senior consultant billing rate is 250 dollars per hour.", "rates.senior_consultant"),

    # ── Policies — versioned ─────────────────────────────────────
    ("The travel policy requires economy class for all flights under six hours.", "policy.travel"),
    ("The travel policy now allows premium economy for flights over four hours.", "policy.travel"),
    ("The remote work policy allows two remote days per week.", "policy.remote"),
    ("The remote work policy was updated to three remote days per week.", "policy.remote"),
    ("Client deliverables require partner review before they are sent.", "policy.review"),
    ("Expense reports are due within 15 days of travel.", "policy.expenses"),

    # ── Best practices / lessons learned ─────────────────────────
    ("Best practice: hold a stakeholder alignment workshop in the first two weeks of every engagement.", None),
    ("Best practice: fixed-fee engagements need a written change-control process before kickoff.", None),
    ("Best practice: assign a single client-side counterpart for every workstream.", None),
    ("Lesson from the Dunmore engagement: weekly steering meetings cut rework substantially.", None),
    ("Lesson from the Caldera engagement: integration timelines slip when the client board meets quarterly.", None),
    ("Lesson from the Northwind engagement: data cleanup took twice the estimated effort.", None),
    ("Best practice: send the weekly status note on Friday before noon.", None),
    ("Best practice: archive every final deliverable in the engagement repository within one week of closing.", None),
]
