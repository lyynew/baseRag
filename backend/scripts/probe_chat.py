"""探测对话模型能力：基础对话 / 流式 / JSON 输出。

这三项决定了 P2 的实现方式：
- 不支持流式 → 前端只能整体输出
- 不支持 json_object → 引用校验要降级为"提示词约束 + 宽松解析"
"""

import asyncio
import pathlib
import re
import time

import httpx

env = pathlib.Path(__file__).resolve().parent.parent / ".env"
text = env.read_text(encoding="utf-8")


def get(key: str) -> str:
    m = re.search(rf"^{key}=(.*)$", text, re.M)
    return m.group(1).split("#")[0].strip() if m else ""


PROVIDERS = {
    "mimo": (get("MIMO_BASE_URL"), get("MIMO_API_KEY"), get("MIMO_MODEL")),
    "deepseek": (get("DEEPSEEK_BASE_URL"), get("DEEPSEEK_API_KEY"), get("DEEPSEEK_MODEL")),
}

PROMPT = "用一句话说明什么是向量检索。"


async def probe(client: httpx.AsyncClient, name: str, base: str, key: str, model: str) -> None:
    print(f"\n{'=' * 60}\n{name}  model={model}  base={base}\n{'=' * 60}")
    if not (base and key and model):
        print("  配置不完整，跳过")
        return
    headers = {"Authorization": f"Bearer {key}"}

    # 1. 非流式
    t0 = time.perf_counter()
    r = await client.post(
        f"{base}/chat/completions",
        headers=headers,
        json={"model": model, "messages": [{"role": "user", "content": PROMPT}], "max_tokens": 100},
    )
    dt = time.perf_counter() - t0
    if r.status_code == 200:
        body = r.json()
        msg = body["choices"][0]["message"].get("content", "")
        print(f"  [OK] 基础对话  {dt:.2f}s  usage={body.get('usage')}")
        print(f"       {msg[:80]}")
        print(f"       finish_reason={body['choices'][0].get('finish_reason')}")
    else:
        print(f"  [FAIL] 基础对话 http={r.status_code} {r.text[:200]}")
        return

    # 2. 流式
    t0 = time.perf_counter()
    chunks, ttft = 0, None
    try:
        async with client.stream(
            "POST",
            f"{base}/chat/completions",
            headers=headers,
            json={
                "model": model,
                "messages": [{"role": "user", "content": PROMPT}],
                "max_tokens": 100,
                "stream": True,
            },
        ) as resp:
            if resp.status_code != 200:
                print(f"  [FAIL] 流式 http={resp.status_code}")
            else:
                async for line in resp.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    data = line[6:]
                    if data.strip() == "[DONE]":
                        break
                    if ttft is None:
                        ttft = time.perf_counter() - t0
                    chunks += 1
                if ttft:
                    print(f"  [OK] 流式  首包 {ttft:.2f}s  共 {chunks} 包")
                else:
                    print("  [FAIL] 流式无数据")
    except Exception as exc:  # noqa: BLE001
        print(f"  [FAIL] 流式 {type(exc).__name__}: {exc}")

    # 3. JSON 输出
    r = await client.post(
        f"{base}/chat/completions",
        headers=headers,
        json={
            "model": model,
            "messages": [
                {"role": "system", "content": "只输出 JSON，格式 {\"answer\": \"...\"}"},
                {"role": "user", "content": "1+1 等于几"},
            ],
            "max_tokens": 100,
            "response_format": {"type": "json_object"},
        },
    )
    if r.status_code == 200:
        content = r.json()["choices"][0]["message"].get("content", "")
        looks_json = content.strip().startswith("{")
        print(f"  [{'OK' if looks_json else 'PART'}] json_object  {content[:80]}")
    else:
        print(f"  [FAIL] json_object http={r.status_code} {r.text[:160]}")


async def main() -> None:
    async with httpx.AsyncClient(timeout=60) as client:
        for name, (base, key, model) in PROVIDERS.items():
            await probe(client, name, base, key, model)


if __name__ == "__main__":
    asyncio.run(main())
