from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from schemas import AgentName


TOKEN_PATTERN = re.compile(r"[a-z0-9][a-z0-9_/-]{2,}")


@dataclass(frozen=True)
class KnowledgeFragment:
    id: str
    title: str
    content: str
    tags: tuple[str, ...]
    agents: tuple[str, ...]
    source: str


class LocalKnowledgeBase:
    """Small keyword retriever. More context is not automatically better."""

    def __init__(self, root: str | Path, max_fragments: int = 5) -> None:
        self.root = Path(root)
        self.max_fragments = max_fragments
        self._fragments = self._load_fragments()

    def get_relevant_knowledge(
        self,
        agent: AgentName,
        query: str,
        limit: int | None = None,
    ) -> list[KnowledgeFragment]:
        capped_limit = min(
            self.max_fragments,
            self.max_fragments if limit is None else max(0, limit),
        )
        if capped_limit == 0:
            return []
        query_tokens = set(TOKEN_PATTERN.findall(query.lower()))
        scored: list[tuple[int, KnowledgeFragment]] = []
        for fragment in self._fragments:
            if fragment.agents and "all" not in fragment.agents and agent.value not in fragment.agents:
                continue
            searchable = " ".join(
                (fragment.title, fragment.content, " ".join(fragment.tags))
            ).lower()
            score = sum(2 if token in fragment.tags else 1 for token in query_tokens if token in searchable)
            if score > 0:
                scored.append((score, fragment))
        scored.sort(key=lambda item: (-item[0], item[1].id))
        return [fragment for _, fragment in scored[:capped_limit]]

    def _load_fragments(self) -> list[KnowledgeFragment]:
        if not self.root.exists():
            return []
        fragments: list[KnowledgeFragment] = []
        for path in sorted(self.root.rglob("*.md")):
            text = path.read_text(encoding="utf-8")
            metadata, body = self._parse_front_matter(text)
            title = next(
                (line.removeprefix("# ").strip() for line in body.splitlines() if line.startswith("# ")),
                path.stem,
            )
            content = " ".join(line.strip() for line in body.splitlines() if line.strip())
            fragments.append(
                KnowledgeFragment(
                    id=path.relative_to(self.root).as_posix(),
                    title=title,
                    content=content[:900],
                    tags=tuple(metadata.get("tags", [])),
                    agents=tuple(metadata.get("agents", [])),
                    source=path.as_posix(),
                )
            )
        return fragments

    @staticmethod
    def _parse_front_matter(text: str) -> tuple[dict[str, list[str]], str]:
        if not text.startswith("---\n"):
            return {}, text
        _, header, body = text.split("---", 2)
        metadata: dict[str, list[str]] = {}
        for line in header.splitlines():
            if ":" not in line:
                continue
            key, value = line.split(":", 1)
            cleaned = value.strip().strip("[]")
            metadata[key.strip()] = [item.strip() for item in cleaned.split(",") if item.strip()]
        return metadata, body
