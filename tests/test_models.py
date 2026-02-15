"""Tests for src/models.py — data model logic."""

from src.models import MealPlanSession, SessionState


class TestMealPlanSession:
    def test_create_defaults_to_idle(self):
        session = MealPlanSession.create(triggered_by="member-1")
        assert session.state == SessionState.IDLE
        assert session.triggered_by == "member-1"
        assert session.id  # UUID should be set

    def test_transition_updates_state(self):
        session = MealPlanSession.create()
        session.transition_to(SessionState.COLLECTING_PREFERENCES)
        assert session.state == SessionState.COLLECTING_PREFERENCES

    def test_transition_updates_timestamps(self):
        session = MealPlanSession.create()
        original_entered = session.state_entered_at
        original_updated = session.updated_at

        session.transition_to(SessionState.GENERATING_PLAN)

        assert session.state_entered_at >= original_entered
        assert session.updated_at >= original_updated

    def test_full_state_sequence(self):
        session = MealPlanSession.create()
        states = [
            SessionState.COLLECTING_PREFERENCES,
            SessionState.GENERATING_PLAN,
            SessionState.AWAITING_APPROVAL,
            SessionState.COMPILING_INGREDIENTS,
            SessionState.CHECKING_PANTRY,
            SessionState.FILLING_CART,
            SessionState.COMPLETED,
        ]
        for state in states:
            session.transition_to(state)
            assert session.state == state

    def test_create_generates_unique_ids(self):
        s1 = MealPlanSession.create()
        s2 = MealPlanSession.create()
        assert s1.id != s2.id
