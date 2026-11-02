"""探测 Milvus 是否支持内置 BM25（Full Text Search）与 hybrid_search。

这是 P1.5 的前置验证：如果 Function/RRFRanker API 不可用，
整个混合检索方案要换（改用手动计算稀疏向量或引入 ES）。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pymilvus
from pymilvus import AnnSearchRequest, DataType, Function, FunctionType, MilvusClient, RRFRanker

from app.core.config import settings

TEST_COLLECTION = "probe_bm25_tmp"
DIM = 8


def main() -> int:
    print(f"pymilvus: {pymilvus.__version__}")
    client = MilvusClient(uri=f"http://{settings.milvus_host}:{settings.milvus_port}")

    try:
        ver = client.get_server_version()
        print(f"milvus server: {ver}")
    except Exception as exc:  # noqa: BLE001
        print(f"取版本失败: {exc}")

    print(f"FunctionType 可用: {hasattr(FunctionType, 'BM25')}")
    if not hasattr(FunctionType, "BM25"):
        print("[FAIL] 当前 pymilvus 不支持内置 BM25")
        return 1

    if client.has_collection(TEST_COLLECTION):
        client.drop_collection(TEST_COLLECTION)

    # 构造带 BM25 函数的 schema
    try:
        schema = client.create_schema(auto_id=False, enable_dynamic_field=False)
        schema.add_field("id", DataType.INT64, is_primary=True)
        schema.add_field("kb_id", DataType.INT64)
        schema.add_field(
            "text",
            DataType.VARCHAR,
            max_length=4096,
            # 两个开关都要：enable_analyzer 让字段可被 analyze，
            # analyzer_params 指定中文分词器（默认 standard 对中文按字切，BM25 基本失效）
            enable_analyzer=True,
            analyzer_params={"type": "chinese"},
            enable_match=True,
        )
        schema.add_field("vector", DataType.FLOAT_VECTOR, dim=DIM)
        schema.add_field("sparse", DataType.SPARSE_FLOAT_VECTOR)
        schema.add_function(
            Function(
                name="bm25_fn",
                input_field_names=["text"],
                output_field_names=["sparse"],
                function_type=FunctionType.BM25,
            )
        )

        idx = client.prepare_index_params()
        idx.add_index(field_name="vector", index_type="FLAT", metric_type="COSINE")
        idx.add_index(
            field_name="sparse",
            index_type="SPARSE_INVERTED_INDEX",
            metric_type="BM25",
        )
        client.create_collection(TEST_COLLECTION, schema=schema, index_params=idx)
        print("[OK] 建表成功（含 chinese analyzer + BM25 function）")
    except Exception as exc:  # noqa: BLE001
        print(f"[FAIL] 建表失败：{type(exc).__name__}: {exc}")
        return 1

    # 插入：只给 text，sparse 由 Milvus 自动生成
    rows = [
        {
            "id": 1,
            "kb_id": 1,
            "text": "服务器型号 DL380 Gen10 硬盘故障率偏高",
            "vector": [1, 0, 0, 0, 0, 0, 0, 0],
        },
        {
            "id": 2,
            "kb_id": 1,
            "text": "员工出差住宿标准为一晚六百元",
            "vector": [0, 1, 0, 0, 0, 0, 0, 0],
        },
        {
            "id": 3,
            "kb_id": 1,
            "text": "数据库每日凌晨三点执行全量备份",
            "vector": [0, 0, 1, 0, 0, 0, 0, 0],
        },
    ]
    try:
        client.insert(TEST_COLLECTION, rows)
        client.flush(TEST_COLLECTION)
        print(f"[OK] 插入 {len(rows)} 条（未提供 sparse，验证自动生成）")
    except Exception as exc:  # noqa: BLE001
        print(f"[FAIL] 插入失败：{type(exc).__name__}: {exc}")
        return 1

    # 纯稀疏检索：搜型号这种精确词，dense 很难，BM25 应该准
    try:
        res = client.search(
            collection_name=TEST_COLLECTION,
            data=["DL380"],
            anns_field="sparse",
            limit=3,
            output_fields=["text"],
        )
        hits = [(r["id"], round(float(r["distance"]), 3)) for r in res[0]] if res else []
        print(f"[OK] 纯 BM25 检索 'DL380' → {hits}")
        ok_sparse = bool(hits) and hits[0][0] == 1
        print(f"     命中正确: {ok_sparse}")
    except Exception as exc:  # noqa: BLE001
        print(f"[FAIL] BM25 检索失败：{type(exc).__name__}: {exc}")
        ok_sparse = False

    # 混合检索
    try:
        reqs = [
            AnnSearchRequest(
                data=[[0.1, 0.9, 0.1, 0, 0, 0, 0, 0]],
                anns_field="vector",
                param={"metric_type": "COSINE"},
                limit=3,
            ),
            AnnSearchRequest(
                data=["住宿 标准"],
                anns_field="sparse",
                param={"metric_type": "BM25"},
                limit=3,
            ),
        ]
        res = client.hybrid_search(
            collection_name=TEST_COLLECTION,
            reqs=reqs,
            ranker=RRFRanker(k=60),
            limit=3,
            output_fields=["text"],
        )
        hits = [(r["id"], round(float(r["distance"]), 4)) for r in res[0]] if res else []
        print(f"[OK] hybrid_search '住宿 标准' → {hits}")
        print(f"     首条正确(id=2): {bool(hits) and hits[0][0] == 2}")
    except Exception as exc:  # noqa: BLE001
        print(f"[FAIL] hybrid_search 失败：{type(exc).__name__}: {exc}")

    client.drop_collection(TEST_COLLECTION)
    print("已清理测试 collection")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
