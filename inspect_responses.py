from pathlib import Path

from openai import OpenAI

from config import get_settings


settings = get_settings()
client = OpenAI(api_key=settings.openai_api_key)

response_ids = [
    "resp_04b72055d9e2a339006a9110cb25c887d2b9c88f60f758d6d5",
]

out_dir = Path("critic_autopsy")
out_dir.mkdir(exist_ok=True)

for response_id in response_ids:
    r = client.responses.retrieve(response_id)

    text = r.output_text or ""

    print("\n" + "=" * 80)
    print("id:", r.id)
    print("status:", r.status)
    print("incomplete:", r.incomplete_details)
    print("model:", r.model)
    print("max_output_tokens:", r.max_output_tokens)
    print("reasoning config:", r.reasoning)
    print("input_tokens:", r.usage.input_tokens)
    print("output_tokens:", r.usage.output_tokens)
    print(
        "reasoning_tokens:",
        r.usage.output_tokens_details.reasoning_tokens,
    )
    print("total_tokens:", r.usage.total_tokens)
    print("visible output chars:", len(text))

    print("\n--- FIRST 800 ---")
    print(repr(text[:800]))

    print("\n--- LAST 800 ---")
    print(repr(text[-800:]))

    path = out_dir / f"{r.id}.txt"
    path.write_text(text, encoding="utf-8")

    print("\nsaved:", path)