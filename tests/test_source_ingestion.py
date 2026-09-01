from __future__ import annotations

from pathlib import Path

import pytest

from schemas import AgentName, KnowledgeSourceType, KnowledgeTopic
from source_ingestion import SourceIngestor


def ingest_markdown(
    tmp_path: Path,
    content: str,
    *,
    topic: KnowledgeTopic = KnowledgeTopic.XSS,
):
    path = tmp_path / "source.md"
    path.write_text(content, encoding="utf-8")
    return SourceIngestor(2000).ingest_file(
        path,
        agent=AgentName.IKIT,
        source_type=KnowledgeSourceType.ACADEMY,
        topic=topic,
    )


def test_frontmatter_sets_canonical_provenance_and_is_not_chunked(
    tmp_path: Path,
) -> None:
    document, chunks = ingest_markdown(
        tmp_path,
        """---
agent: ikit
topic: xss
subtopic: "overview"
source_type: academy
source_title: "Cross-site scripting"
source_reference: "https://portswigger.net/web-security/cross-site-scripting"
corpus: ikit_xss_core_v1
---

# Cross-site scripting

Execution must be demonstrated separately from reflection.
""",
    )

    assert document.title == "Cross-site scripting"
    assert document.source_reference == (
        "https://portswigger.net/web-security/cross-site-scripting"
    )
    assert document.source_path == str((tmp_path / "source.md").resolve())
    assert document.corpus == "ikit_xss_core_v1"
    assert document.subtopic == "overview"
    assert not document.content.startswith("---")
    assert len(chunks) == 1
    assert chunks[0].source_reference == document.source_reference
    assert "agent: ikit" not in chunks[0].content
    assert "source_reference:" not in chunks[0].content


def test_explicit_routing_metadata_mismatch_fails_clearly(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="frontmatter topic=.*conflicts with explicit topic"):
        ingest_markdown(
            tmp_path,
            """---
agent: ikit
topic: sqli
source_type: academy
source_title: SQL injection
source_reference: https://example.test/sqli
corpus: test
---

# SQL injection

Technical source content.
""",
            topic=KnowledgeTopic.XSS,
        )


@pytest.mark.parametrize(
    ("content", "message"),
    [
        (
            "---\nagent: ikit\ntopic: xss\n# Missing delimiter\n",
            "missing closing",
        ),
        (
            """---
agent: ikit
topic: xss
topic: sqli
source_type: academy
---

# Source

Content.
""",
            "duplicate field topic",
        ),
    ],
)
def test_malformed_or_contradictory_frontmatter_is_rejected(
    tmp_path: Path,
    content: str,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        ingest_markdown(tmp_path, content)


def test_read_more_link_only_section_is_not_queued(tmp_path: Path) -> None:
    _, chunks = ingest_markdown(
        tmp_path,
        """# Supported method

Confirm the parser context before claiming execution.

#### Read more

- [Reflected XSS](https://example.test/reflected)
- [Cheat sheet](https://example.test/cheat-sheet)
""",
    )

    assert [chunk.heading for chunk in chunks] == ["Supported method"]
    assert all("Cheat sheet" not in chunk.content for chunk in chunks)


def test_prose_containing_links_is_preserved(tmp_path: Path) -> None:
    _, chunks = ingest_markdown(
        tmp_path,
        """# Context method

Use the [context guide](https://example.test/context) after locating the reflected value.
""",
    )

    assert len(chunks) == 1
    assert "after locating the reflected value" in chunks[0].content


def test_technical_link_list_is_preserved_even_under_navigation_heading(
    tmp_path: Path,
) -> None:
    _, chunks = ingest_markdown(
        tmp_path,
        """#### Read more

- Use [developer tools](https://example.test/devtools) to inspect the parsed DOM context.
- Compare the [response](https://example.test/response) with the rendered result.
""",
    )

    assert len(chunks) == 1
    assert chunks[0].heading == "Read more"
    assert "inspect the parsed DOM context" in chunks[0].content
