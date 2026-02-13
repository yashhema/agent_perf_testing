"""Tests for the state machine transitions."""

import pytest
from unittest.mock import MagicMock

from orchestrator.core.state_machine import (
    FORWARD_SEQUENCE,
    TRANSITIONS,
    fail,
    next_forward_state,
    transition,
    update_substates,
)
from orchestrator.models.enums import TestRunState


class TestTransitions:
    def test_valid_transitions_defined(self):
        """All forward states have valid transitions."""
        for state in FORWARD_SEQUENCE:
            assert state in TRANSITIONS

    def test_forward_sequence(self):
        """Forward sequence is in correct order."""
        expected = [
            TestRunState.created,
            TestRunState.validating,
            TestRunState.setting_up,
            TestRunState.calibrating,
            TestRunState.generating_sequences,
            TestRunState.executing,
            TestRunState.comparing,
            TestRunState.completed,
        ]
        assert FORWARD_SEQUENCE == expected

    def test_next_forward_state(self):
        assert next_forward_state(TestRunState.validating) == TestRunState.setting_up
        assert next_forward_state(TestRunState.executing) == TestRunState.comparing
        assert next_forward_state(TestRunState.comparing) == TestRunState.completed
        assert next_forward_state(TestRunState.completed) is None

    def test_transition_created_to_validating(self, session, sample_test_run):
        """Valid transition from created to validating."""
        assert sample_test_run.state == TestRunState.created
        transition(session, sample_test_run, TestRunState.validating)
        assert sample_test_run.state == TestRunState.validating
        assert sample_test_run.started_at is not None

    def test_transition_valid(self, session, sample_test_run):
        """Valid transition updates state."""
        transition(session, sample_test_run, TestRunState.validating)
        transition(session, sample_test_run, TestRunState.setting_up)
        assert sample_test_run.state == TestRunState.setting_up

    def test_transition_invalid(self, session, sample_test_run):
        """Invalid transition raises ValueError."""
        transition(session, sample_test_run, TestRunState.validating)
        with pytest.raises(ValueError):
            transition(session, sample_test_run, TestRunState.executing)

    def test_fail(self, session, sample_test_run):
        """fail() sets state to failed with error message."""
        transition(session, sample_test_run, TestRunState.validating)
        transition(session, sample_test_run, TestRunState.setting_up)
        transition(session, sample_test_run, TestRunState.calibrating)
        transition(session, sample_test_run, TestRunState.generating_sequences)
        transition(session, sample_test_run, TestRunState.executing)
        fail(session, sample_test_run, "Something broke")
        assert sample_test_run.state == TestRunState.failed
        assert sample_test_run.error_message == "Something broke"

    def test_update_substates(self, session, sample_test_run, sample_load_profile):
        """update_substates sets the current snapshot/profile/cycle."""
        update_substates(
            session, sample_test_run,
            snapshot_num=1,
            load_profile_id=sample_load_profile.id,
            cycle_number=2,
        )
        assert sample_test_run.current_snapshot_num == 1
        assert sample_test_run.current_load_profile_id == sample_load_profile.id
        assert sample_test_run.current_cycle_number == 2
