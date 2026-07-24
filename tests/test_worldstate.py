from controller_service.worldstate import parse_ssg, situation_lines

# The tick that produced 37 consecutive GatherWood decisions in
# logs/decisions-20260723-003334: wood in hand, blueprints starved of stone.
STUCK_SSG = """self: health 90, carrying wood 36
player: 6m behind, healthy, holding
wood W1: 2m ahead
farther deposits (15m+): 1 total (nearest T1: 23m right)
blueprint B2: 5m ahead-left, Wall [Wood 0/2, Stone 0/1]
blueprint B1: 5m left, Wall [Wood 0/2, Stone 0/1]
farther blueprints (15m+): 13 total (nearest B7: 6m ahead-right)
bed: 13m behind-right
world: day 1, monsters left 0"""

COMBAT_SSG = """self: health 70, carrying wood 4, stone 2
player: 11m ahead-right, hurt, moving
zombie Z1: 6m right, healthy, chasing you, LOS to you: yes, threatening
skeleton S1: 40m left, hurt, wandering, LOS to you: yes
zombie Z9: last seen 12m behind 6s ago
cover C2: 4m left, blocks Z1
wall D1: 4m left, Wall 62% · costs Wood
farther wood (15m+): 3 total (nearest W7: 22m behind)
farther stone (15m+): 1 total (nearest T2: 30m right)
world: day 2, monsters left 4"""


def test_parses_carrying_and_blueprint_needs():
    state = parse_ssg(STUCK_SSG)
    assert state.carrying == {"wood": 36}
    assert [bp.id for bp in state.blueprints] == ["B2", "B1"]
    assert state.blueprints[0].remaining == {"wood": 2, "stone": 1}
    assert state.far_counts == {"deposits": 1, "blueprints": 13}


def test_stuck_tick_reports_surplus_wood_and_missing_stone():
    state = parse_ssg(STUCK_SSG)
    assert state.missing() == ["stone"]
    assert state.surplus() == ["wood"]
    assert ("B2", "wood") in state.depositable()

    block = "\n".join(situation_lines(state))
    assert "you CAN deposit right now" in block
    assert "MISSING stone" in block
    assert "ENOUGH wood" in block


def test_remembered_contacts_are_not_threats():
    state = parse_ssg(COMBAT_SSG)
    assert [t.id for t in state.threats] == ["Z1", "S1"]
    nearest = state.nearest_threat
    assert nearest.id == "Z1" and nearest.dist_m == 6 and nearest.threatening


def test_damaged_wall_repair_cost_is_matched_against_inventory():
    state = parse_ssg(COMBAT_SSG)
    assert [w.repair_item for w in state.walls] == ["wood"]
    assert [w.id for w in state.repairable()] == ["D1"]


def test_cover_is_not_mistaken_for_an_enemy_contact():
    # "cover C2: ..." has the same shape as a contact line; reading a wall as
    # something to fight (or fight through) is the dangerous failure here.
    state = parse_ssg(COMBAT_SSG)
    assert [t.id for t in state.threats] == ["Z1", "S1"]
    assert [(c.id, c.blocks) for c in state.covers] == [("C2", "Z1")]

    block = "\n".join(situation_lines(state))
    assert "nearest C2 at 4m, shields you from Z1" in block


def test_far_deposits_are_reported_per_resource():
    state = parse_ssg(COMBAT_SSG)
    assert state.far_counts["wood"] == 3 and state.far_counts["stone"] == 1

    block = "\n".join(situation_lines(state))
    assert "wood W7, 22m away" in block
    assert "stone T2, 30m away" in block


def test_target_kinds_keep_ids_in_their_own_category():
    kinds = parse_ssg(COMBAT_SSG).ids_by_kind()
    assert kinds["cover"] == {"C2"}
    assert kinds["threat"] == {"Z1", "S1"}
    assert kinds["wall"] == {"D1"}
    assert kinds["wood"] == {"W7"} and kinds["stone"] == {"T2"}


def test_unparsable_ssg_yields_empty_state_not_an_error():
    state = parse_ssg("total gibberish\n\n???")
    assert state.carrying == {} and state.blueprints == [] and state.threats == []
    assert situation_lines(state)          # still renders a usable block
