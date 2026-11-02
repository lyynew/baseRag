"""探测百炼 Embedding 模型可用性与维度。"""

import pathlib
import re

import httpx

env = pathlib.Path(__file__).resolve().parent.parent / ".env"
text = env.read_text(encoding="utf-8")


def get(key: str) -> str:
    m = re.search(rf"^{key}=(.*)$", text, re.M)
    return m.group(1).split("#")[0].strip() if m else ""


key = get("DASHSCOPE_API_KEY")
base = get("DASHSCOPE_BASE_URL").rstrip("/")
print(f"base_url={base}  key_prefix={key[:8]}***\n")

candidates = [
    "qwen3.7-text-embedding-flash",
    "qwen3-text-embedding-flash",
    "text-embedding-v4",
    "text-embedding-v3",
]

for model in candidates:
    try:
        r = httpx.post(
            f"{base}/embeddings",
            headers={"Authorization": f"Bearer {key}"},
            json={"model": model, "input": ["知识库检索测试"]},
            timeout=30,
        )
        if r.status_code == 200:
            body = r.json()
            dim = len(body["data"][0]["embedding"])
            print(f"[OK]   {model}  dim={dim}  usage={body.get('usage')}")
        else:
            msg = r.text[:180].replace("\n", " ")
            print(f"[FAIL] {model}  http={r.status_code}  {msg}")
    except Exception as exc:  # noqa: BLE001
        print(f"[ERR]  {model}  {type(exc).__name__}: {exc}")
