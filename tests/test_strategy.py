"""Tests for strategy_selector()."""
from unittest.mock import patch
import orchestrator


@patch("builtins.input", return_value="1")
def test_strategy_5k(mock_input):
    """Selecting '1' returns 5k target."""
    result = orchestrator.strategy_selector()
    assert result == ["5k"]


@patch("builtins.input", return_value="2")
def test_strategy_1080p(mock_input):
    """Selecting '2' returns 1080p target."""
    result = orchestrator.strategy_selector()
    assert result == ["1080p"]


@patch("builtins.input", return_value="3")
def test_strategy_both(mock_input):
    """Selecting '3' returns both targets."""
    result = orchestrator.strategy_selector()
    assert result == ["5k", "1080p"]


@patch("builtins.input", side_effect=["x", "abc", "2"])
def test_strategy_retries_on_invalid_input(mock_input):
    """Invalid inputs should be retried until a valid choice is given."""
    result = orchestrator.strategy_selector()
    assert result == ["1080p"]
    assert mock_input.call_count == 3
