"""O gestor só escolhe dentro do que o rito permite."""

from app.domain.steward import legal_actions


def _case(**overrides):
    data = {
        "status": "draft",
        "procedure_conclusion": None,
        "documents": [],
        "consent": {
            "complete": False,
            "claimant": {"accepted": False},
            "respondent": {"accepted": False},
        },
        "submission": {
            "complete": False,
            "claimant": {"ready": False},
            "respondent": {"ready": False},
        },
        "contradictory": {"complete": False},
        "manifest_locked": False,
        "organized": None,
        "decision": None,
        "review": None,
        "conciliation_rounds": [],
    }
    data.update(overrides)
    return data


def test_steward_waits_until_both_presentations_are_closed():
    case = _case(
        documents=[{"id": "d1", "admitted": True, "acknowledged_at": "t", "response_status": "answered"}],
        consent={"complete": True},
        contradictory={"complete": True},
        submission={
            "complete": False,
            "claimant": {"ready": True},
            "respondent": {"ready": False},
        },
    )
    assert legal_actions(case)["actions"] == ["wait"]


def test_steward_locks_only_after_both_presentations_and_contradictory():
    case = _case(
        documents=[{"id": "d1", "admitted": True}],
        consent={"complete": True},
        contradictory={"complete": True},
        submission={
            "complete": True,
            "claimant": {"ready": True},
            "respondent": {"ready": True},
        },
    )
    assert legal_actions(case)["actions"] == ["lock"]


def test_new_position_allows_another_round_or_judgment():
    case = _case(
        status="conciliation",
        manifest_locked=True,
        consent={"complete": True},
        contradictory={"complete": True},
        submission={"complete": True, "claimant": {"ready": True}, "respondent": {"ready": True}},
        conciliation_rounds=[
            {
                "round_number": 1,
                "continue_recommended": False,
                "party_positions": {
                    "claimant": {"text": "Novo prazo é possível.", "waived": False},
                    "respondent": {"text": "", "waived": True},
                },
            }
        ],
    )
    assert legal_actions(case)["actions"] == ["conciliate", "organize"]


def test_both_waivers_end_composition():
    case = _case(
        status="conciliation",
        manifest_locked=True,
        conciliation_rounds=[
            {
                "round_number": 1,
                "continue_recommended": True,
                "party_positions": {
                    "claimant": {"text": "", "waived": True},
                    "respondent": {"text": "", "waived": True},
                },
            }
        ],
    )
    assert legal_actions(case)["actions"] == ["organize"]
