"""探测百炼 Rerank（gte-rerank-v2）可用性。

Rerank 走的是 DashScope 原生接口，不是 OpenAI 兼容协议，所以单独封装。
"""

import pathlib
import re

import httpx

env = pathlib.Path(__file__).resolve().parent.parent / ".env"
text = env.read_text(encoding="utf-8")


def get(key: str) -> str:
    m = re.search(rf"^{key}=(.*)$", text, re.M)
    return m.group(1).split("#")[0].strip() if m else ""


key = get("DASHSCOPE_API_KEY")
url = "https://dashscope.aliyuncs.com/api/v1/services/rerank/text-rerank/text-rerank"

query = "出差住酒店一晚最多能报多少钱"
documents = [
    "交通标准：高铁二等座、飞机经济舱。市内交通凭票据实报实销，单日上限 100 元。",
    "住宿标准：一线城市每晚不超过 600 元，二线城市不超过 400 元，其他城市不超过 300 元。",
    "每日凌晨 2 点自动巡检一次，巡检项包括磁盘使用率、CPU 负载、内存占用和关键进程存活。",
]

payload = {
    "model": "gte-rerank-v2",
    "input": {"query": query, "documents": documents},
    "parameters": {"return_documents": False, "top_n": 3},
}

try:
    r = httpx.post(url, headers={"Authorization": f"Bearer {key}"}, json=payload, timeout=30)
    print(f"http={r.status_code}")
    if r.status_code == 200:
        body = r.json()
        print("usage:", body.get("usage"))
        for i, item in enumerate(body["output"]["results"], 1):
            print(f"  #{i} index={item['index']} score={item['relevance_score']:.4f}")
    else:
        print(r.text[:400])
except Exception as exc:  # noqa: BLE001
    print(f"ERR {type(exc).__name__}: {exc}")
