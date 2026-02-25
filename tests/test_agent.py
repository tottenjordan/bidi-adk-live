# tests/test_agent.py
"""Tests for the home appliance detector agent configuration."""

import pytest


class TestAgentConfiguration:
    """Verify the agent is properly configured."""

    def test_agent_exists_and_is_importable(self):
        """Agent can be imported from the package."""
        from app.home_agent import agent

        assert agent is not None

    def test_agent_name(self):
        """Agent has the correct name."""
        from app.home_agent import agent

        assert agent.name == "home_appliance_detector"

    def test_agent_model_is_set(self):
        """Agent has a model configured."""
        from app.home_agent import agent

        assert agent.model is not None

    def test_agent_has_log_appliance_tool(self):
        """Agent has the log_appliance_bq tool registered."""
        from app.home_agent import agent

        tool_names = [t.__name__ if callable(t) else str(t) for t in agent.tools]
        assert "log_appliance_bq" in tool_names

    def test_agent_has_instruction(self):
        """Agent has a non-empty instruction."""
        from app.home_agent import agent

        assert agent.instruction is not None
        assert len(agent.instruction) > 0

    def test_agent_instruction_mentions_appliances(self):
        """Agent instruction references appliance detection."""
        from app.home_agent import agent

        instruction = agent.instruction.lower()
        assert "appliance" in instruction

    def test_agent_instruction_mentions_confirmation(self):
        """Agent instruction tells it to confirm with user before logging."""
        from app.home_agent import agent

        instruction = agent.instruction.lower()
        assert "confirm" in instruction
