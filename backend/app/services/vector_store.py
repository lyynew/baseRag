"""Milvus 向量存储封装。

设计要点（对应技术选型 §6.1）：
- 一个 collection 装所有知识库，用 kb_id 做标量过滤，**不要每库一个 collection**
- 主键直接用 MySQL 的 chunk_id，避免维护两套 ID 映射
- 相似度 COSINE（百炼返回的向量已归一化）
- 删除用主键 delete，Milvus 是标记删除，量大后需 compact
"""

from dataclasses import dataclass
from typing import Any

from pymilvus import (
    AnnSearchRequest,
    DataType,
    Function,
    FunctionType,
    MilvusClient,
    RRFRanker,
)

from app.core.config import settings
from app.core.errors import AppError, ErrorCode
from app.core.logging import get_logger

logger = get_logger(__name__)

CONTENT_MAX_LEN = 8192


@dataclass
class VectorHit:
    chunk_id: int
    doc_id: int
    kb_id: int
    content: str
    score: float


class VectorStore:
    def __init__(
        self,
        uri: str | None = None,
        collection: str | None = None,
        dim: int | None = None,
    ) -> None:
        self.uri = uri or f"http://{settings.milvus_host}:{settings.milvus_port}"
        self.collection = collection or settings.milvus_collection
        self.dim = dim or settings.milvus_vector_dim
        self._client: MilvusClient | None = None

    @property
    def client(self) -> MilvusClient:
        if self._client is None:
            self._client = MilvusClient(uri=self.uri, timeout=10)
        return self._client

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

    # ---------------- schema ----------------
    def ensure_collection(self, drop_existing: bool = False) -> str:
        """创建 collection（幂等）。存在则直接返回。

        schema 同时支持稠密向量与全文稀疏向量：
        - vector：百炼 embedding，负责语义相似
        - sparse：Milvus 内置 BM25 从 content 自动生成，负责精确词命中（型号、编号、人名）
        中文必须指定 chinese analyzer，否则 standard analyzer 按单字切分，BM25 基本失效。
        """
        exists = self.client.has_collection(self.collection)
        if exists and drop_existing:
            self.client.drop_collection(self.collection)
            exists = False
            logger.warning("collection_dropped", collection=self.collection)
        if exists:
            return "exists"

        schema = self.client.create_schema(auto_id=False, enable_dynamic_field=False)
        schema.add_field("id", DataType.INT64, is_primary=True, description="等于 MySQL chunk.id")
        schema.add_field("kb_id", DataType.INT64, description="知识库，检索过滤用")
        schema.add_field("doc_id", DataType.INT64, description="文档，删除用")
        schema.add_field(
            "content",
            DataType.VARCHAR,
            max_length=CONTENT_MAX_LEN,
            # BM25 要求输入字段开启 analyzer，并用中文分词器
            enable_analyzer=True,
            analyzer_params={"type": "chinese"},
            enable_match=True,
        )
        schema.add_field("vector", DataType.FLOAT_VECTOR, dim=self.dim)
        schema.add_field("sparse", DataType.SPARSE_FLOAT_VECTOR, description="BM25 自动生成")
        schema.add_function(
            Function(
                name="bm25",
                input_field_names=["content"],
                output_field_names=["sparse"],
                function_type=FunctionType.BM25,
            )
        )

        index_params = self.client.prepare_index_params()
        index_params.add_index(
            field_name="vector",
            index_type=settings.milvus_index_type,
            metric_type=settings.milvus_metric_type,
            params={"M": 16, "efConstruction": 200},
        )
        index_params.add_index(
            field_name="sparse",
            index_type="SPARSE_INVERTED_INDEX",
            metric_type="BM25",
        )
        # kb_id 建标量索引，否则带知识库过滤的检索会退化成全量扫描
        index_params.add_index(field_name="kb_id", index_type="INVERTED")

        self.client.create_collection(
            collection_name=self.collection,
            schema=schema,
            index_params=index_params,
        )
        logger.info("collection_created", collection=self.collection, dim=self.dim, bm25=True)
        return "created"

    # ---------------- 写入 ----------------
    def upsert(self, rows: list[dict[str, Any]]) -> int:
        """rows: [{id, kb_id, doc_id, content, vector}]，多余字段会被丢弃。"""
        if not rows:
            return 0
        allowed = ("id", "kb_id", "doc_id", "content", "vector")
        clean: list[dict[str, Any]] = []
        for r in rows:
            item = {k: r[k] for k in allowed if k in r}
            if len(item.get("content", "")) > CONTENT_MAX_LEN:
                item["content"] = item["content"][:CONTENT_MAX_LEN]
            clean.append(item)

        self.client.upsert(collection_name=self.collection, data=clean)
        # 立即 flush，保证"上传后马上提问"能查到（growing segment 的坑）
        self.client.flush(self.collection)
        logger.info("vectors_upserted", count=len(clean), collection=self.collection)
        return len(clean)

    def delete_by_ids(self, ids: list[int]) -> None:
        if not ids:
            return
        self.client.delete(collection_name=self.collection, ids=ids)
        self.client.flush(self.collection)

    def delete_by_doc(self, doc_id: int) -> None:
        self.client.delete(collection_name=self.collection, filter=f"doc_id == {doc_id}")
        self.client.flush(self.collection)

    def delete_by_kb(self, kb_id: int) -> None:
        """删除整个知识库的向量。删库时必须调用，否则会留下永远查不到的孤儿向量。"""
        self.client.delete(collection_name=self.collection, filter=f"kb_id == {kb_id}")
        self.client.flush(self.collection)
        logger.info("vectors_deleted_by_kb", kb_id=kb_id)

    def count(self, expr: str | None = None) -> int:
        try:
            res = self.client.query(
                collection_name=self.collection,
                filter=expr or "id >= 0",
                output_fields=["count(*)"],
            )
            return int(res[0]["count(*)"]) if res else 0
        except Exception as exc:  # noqa: BLE001
            logger.warning("milvus_count_failed", error=str(exc))
            return -1

    # ---------------- 检索 ----------------
    def hybrid_search(
        self,
        vector: list[float],
        query_text: str,
        kb_ids: list[int],
        top_k: int = 30,
        rrf_k: int = 60,
    ) -> list[VectorHit]:
        """稠密 + BM25 稀疏双路召回，RRF 融合。

        为什么要混合：dense 擅长语义近似（"住宿标准" ↔ "酒店报销"），
        但对型号、编号、人名这类精确 token 很弱 —— 这类查询 BM25 反而更准。
        RRF 只看排名不看分数，所以两路分数量纲不同也能融合。

        注意：返回的 score 是 RRF 融合分（约 0.01~0.05），**不再是余弦相似度**，
        不能拿 0.2 这种余弦阈值去过滤，否则会全军覆没。质量判断交给 rerank。
        """
        if not kb_ids:
            raise AppError("未指定知识库", code=ErrorCode.VALIDATION_ERROR, status_code=400)

        expr = f"kb_id in [{','.join(str(int(k)) for k in kb_ids)}]"

        reqs = [
            AnnSearchRequest(
                data=[vector],
                anns_field="vector",
                param={"metric_type": settings.milvus_metric_type, "params": {"ef": 64}},
                limit=top_k,
                expr=expr,
            ),
            AnnSearchRequest(
                data=[query_text],
                anns_field="sparse",
                param={"metric_type": "BM25"},
                limit=top_k,
                expr=expr,
            ),
        ]

        results = self.client.hybrid_search(
            collection_name=self.collection,
            reqs=reqs,
            ranker=RRFRanker(k=rrf_k),
            limit=top_k,
            output_fields=["kb_id", "doc_id", "content"],
        )

        hits: list[VectorHit] = []
        for row in results[0] if results else []:
            entity = row.get("entity", {})
            hits.append(
                VectorHit(
                    chunk_id=int(row["id"]),
                    doc_id=int(entity.get("doc_id", 0)),
                    kb_id=int(entity.get("kb_id", 0)),
                    content=str(entity.get("content", "")),
                    score=float(row.get("distance", 0.0)),
                )
            )
        return hits

    def search(
        self,
        vector: list[float],
        kb_ids: list[int],
        top_k: int = 30,
        score_threshold: float | None = None,
    ) -> list[VectorHit]:
        """纯向量检索（降级路径）。分数是 COSINE，可直接用阈值过滤。"""
        if not kb_ids:
            raise AppError("未指定知识库", code=ErrorCode.VALIDATION_ERROR, status_code=400)

        # 用 in 过滤，一次查多个库；kb_id 有标量索引
        expr = f"kb_id in [{','.join(str(int(k)) for k in kb_ids)}]"

        results = self.client.search(
            collection_name=self.collection,
            data=[vector],
            # 集合里同时有 vector 与 sparse 两个向量字段，纯向量检索必须显式指定字段
            anns_field="vector",
            filter=expr,
            limit=top_k,
            output_fields=["kb_id", "doc_id", "content"],
            search_params={"metric_type": settings.milvus_metric_type, "params": {"ef": 64}},
        )

        hits: list[VectorHit] = []
        for row in results[0] if results else []:
            entity = row.get("entity", {})
            score = float(row.get("distance", 0.0))
            if score_threshold is not None and score < score_threshold:
                continue
            hits.append(
                VectorHit(
                    chunk_id=int(row["id"]),
                    doc_id=int(entity.get("doc_id", 0)),
                    kb_id=int(entity.get("kb_id", 0)),
                    content=str(entity.get("content", "")),
                    score=score,
                )
            )
        return hits


_store: VectorStore | None = None


def get_vector_store() -> VectorStore:
    global _store
    if _store is None:
        _store = VectorStore()
    return _store
