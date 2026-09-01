from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from llm import LLMBackend, LLMResult
from schemas import AgentName


@dataclass(frozen=True)
class LogicalAgent:
    name: AgentName
    prompt: str
    llm: LLMBackend

    async def run(self, user_input: str, context: str = "") -> LLMResult:
        return await self.llm.ask_agent(
            agent=self.name,
            system_prompt=self.prompt,
            user_input=user_input,
            context=context,
        )


class AgentRegistry:
    def __init__(self, llm: LLMBackend, prompts_dir: Path | None = None) -> None:
        base = prompts_dir or Path(__file__).parent / "prompts"
        self._agents = {
            name: LogicalAgent(name=name, prompt=self._read_prompt(base, name), llm=llm)
            for name in AgentName
        }

    @staticmethod
    def _read_prompt(base: Path, name: AgentName) -> str:
        path = base / f"{name.value}.txt"
        return path.read_text(encoding="utf-8")

    def get(self, name: AgentName) -> LogicalAgent:
        return self._agents[name]
