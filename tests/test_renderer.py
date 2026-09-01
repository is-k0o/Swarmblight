from renderer import DiscordRenderer
from schemas import (
    AgentName,
    Hypothesis,
    Priority,
    StructuredAgentResponse,
    MessageType,
)


def sample_response() -> StructuredAgentResponse:
    return StructuredAgentResponse(
        agent=AgentName.QUEEK,
        message_type=MessageType.HYPOTHESIS,
        summary="The server-side price authority is unknown.",
        observations=["The request contains a price field."],
        hypotheses=[
            Hypothesis(
                title="Client price authority",
                description="The server may trust the submitted price.",
                author_agent=AgentName.QUEEK,
                priority=Priority.HIGH,
            )
        ],
        priority=Priority.HIGH,
        confidence=0.5,
        reasoning_summary="A client field exists, but server behavior is not shown.",
        recommended_next_steps=["Compare submitted and server-calculated price."],
    )


def test_renderer_normal_mode_is_technical() -> None:
    rendered = DiscordRenderer(skaven_level=0).render_response(sample_response())
    assert "QUEEK" in rendered
    assert "Client price authority" in rendered
    assert "BIG CHEESE" not in rendered


def test_renderer_skaven_mode_keeps_technical_content() -> None:
    rendered = DiscordRenderer(skaven_level=2).render_response(sample_response())
    assert "yes-yes" in rendered
    assert "BIG CHEESE" in rendered
    assert "The server may trust the submitted price." in rendered
