from pathlib import Path

from knowledge import LocalKnowledgeBase
from schemas import AgentName


KNOWLEDGE_ROOT = Path(__file__).parents[1] / "knowledge"


def test_retrieval_is_limited_to_max_fragments() -> None:
    knowledge = LocalKnowledgeBase(KNOWLEDGE_ROOT, max_fragments=1)

    fragments = knowledge.get_relevant_knowledge(
        AgentName.QUEEK,
        "methodology evidence scope authorization ownership price",
        limit=5,
    )

    assert len(fragments) == 1


def test_only_relevant_agent_fragments_are_returned() -> None:
    knowledge = LocalKnowledgeBase(KNOWLEDGE_ROOT, max_fragments=5)

    fragments = knowledge.get_relevant_knowledge(
        AgentName.IKIT, "xss source parser sink execution"
    )

    assert fragments
    assert any("ikit" in fragment.id for fragment in fragments)
    assert all("queek" not in fragment.id for fragment in fragments)
