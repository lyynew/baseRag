"""冒烟脚本共享：确保存在一个绑定指定知识库的已发布智能体。

会话接口已改为必须绑定智能体（P6），各冒烟脚本用这个 helper 拿 agent_id。
幂等：优先复用已绑定了该库的已发布智能体，没有才创建。
"""

import httpx


def ensure_published_agent(c: httpx.Client, H: dict, kb_id: int) -> int:
    rows = c.get("/api/v1/admin/agents", headers=H).json()
    for a in rows:
        if a.get("is_published") and kb_id in (a.get("kb_ids") or []):
            return a["id"]

    r = c.post(
        "/api/v1/admin/agents",
        headers=H,
        json={
            "name": f"冒烟专用-库{kb_id}",
            "description": "smoke 脚本自动创建，可删除",
            "kb_ids": [kb_id],
            "is_published": True,
        },
    )
    r.raise_for_status()
    return r.json()["id"]
