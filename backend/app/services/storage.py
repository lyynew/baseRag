"""对象存储（MinIO）。

原则：原始文件绝不进 MySQL，也绝不整体读进内存。
上传走「边接收边落临时文件 → 计算 sha256 → 流式推给 MinIO」，
200MB 文件的内存占用恒定在 1MB 左右。

minio SDK 是同步的，在 async 环境里用 anyio 线程池包装，避免阻塞事件循环。
"""

import hashlib
import tempfile
from pathlib import Path
from typing import BinaryIO

import anyio
from minio import Minio
from minio.error import S3Error

from app.core.config import settings
from app.core.errors import AppError, ErrorCode
from app.core.logging import get_logger

logger = get_logger(__name__)

CHUNK_SIZE = 1024 * 1024  # 1MB


class StorageService:
    def __init__(self) -> None:
        self.bucket = settings.minio_bucket
        self._bucket_ready = False
        self._client = Minio(
            settings.minio_endpoint,
            access_key=settings.minio_access_key,
            secret_key=settings.minio_secret_key,
            secure=settings.minio_secure,
        )

    # ---------------- bucket ----------------
    def _ensure_bucket_sync(self) -> None:
        if not self._client.bucket_exists(self.bucket):
            self._client.make_bucket(self.bucket)
            logger.info("minio_bucket_created", bucket=self.bucket)
        self._bucket_ready = True

    async def ensure_bucket(self, *, force: bool = False) -> None:
        if self._bucket_ready and not force:
            return
        try:
            await anyio.to_thread.run_sync(self._ensure_bucket_sync)
        except S3Error as exc:
            raise AppError(
                f"对象存储不可用：{exc.code}",
                code=ErrorCode.INTERNAL_ERROR,
                status_code=503,
            ) from exc

    # ---------------- 上传 ----------------
    def _put_sync(self, path: str, key: str, content_type: str) -> None:
        self._client.fput_object(
            bucket_name=self.bucket,
            object_name=key,
            file_path=path,
            content_type=content_type,
        )

    async def save_upload(
        self,
        stream: BinaryIO,
        key: str,
        content_type: str = "application/octet-stream",
        max_bytes: int | None = None,
    ) -> tuple[int, str]:
        """把上传流写入对象存储，返回 (大小, sha256)。

        边写临时文件边算摘要，最后一次性推给 MinIO，内存占用恒定。
        """
        max_bytes = max_bytes or settings.max_file_size_mb * 1024 * 1024
        await self.ensure_bucket()
        digest = hashlib.sha256()
        size = 0

        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".upload")
        tmp_path = tmp.name
        try:
            while True:
                chunk = await anyio.to_thread.run_sync(stream.read, CHUNK_SIZE)
                if not chunk:
                    break
                size += len(chunk)
                if size > max_bytes:
                    raise AppError(
                        f"文件超过上限 {settings.max_file_size_mb}MB",
                        code=ErrorCode.FILE_TOO_LARGE,
                        status_code=413,
                    )
                digest.update(chunk)
                await anyio.to_thread.run_sync(tmp.write, chunk)

            tmp.close()
            await anyio.to_thread.run_sync(self._put_sync, tmp_path, key, content_type)
        except AppError:
            raise
        except S3Error as exc:
            raise AppError(
                f"文件写入对象存储失败：{exc.code}",
                code=ErrorCode.INTERNAL_ERROR,
                status_code=503,
            ) from exc
        finally:
            Path(tmp_path).unlink(missing_ok=True)

        logger.info("file_saved", key=key, size=size, sha256=digest.hexdigest()[:12])
        return size, digest.hexdigest()

    # ---------------- 读取与删除 ----------------
    def _download_sync(self, key: str, dest: str) -> None:
        self._client.fget_object(self.bucket, key, dest)

    async def download_to_temp(self, key: str) -> Path:
        """下载到临时文件供解析器读取（解析库都要求本地路径）。"""
        suffix = Path(key).suffix or ".bin"
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
        tmp.close()
        try:
            await anyio.to_thread.run_sync(self._download_sync, key, tmp.name)
        except S3Error as exc:
            Path(tmp.name).unlink(missing_ok=True)
            raise AppError(
                f"读取原始文件失败：{exc.code}",
                code=ErrorCode.NOT_FOUND,
                status_code=404,
            ) from exc
        return Path(tmp.name)

    def _remove_sync(self, key: str) -> None:
        self._client.remove_object(self.bucket, key)

    async def delete(self, key: str) -> None:
        try:
            await anyio.to_thread.run_sync(self._remove_sync, key)
        except S3Error as exc:
            # 删除失败不应阻断业务（记录后继续）
            logger.warning("minio_delete_failed", key=key, error=exc.code)

    @staticmethod
    def build_key(kb_id: int, doc_id: int, filename: str) -> str:
        """对象键：kb_{kb_id}/{doc_id}/{filename}，便于按库批量清理。"""
        safe_name = Path(filename).name.replace("\\", "_").replace("/", "_")
        return f"kb_{kb_id}/{doc_id}/{safe_name}"


_storage: StorageService | None = None


def get_storage() -> StorageService:
    global _storage
    if _storage is None:
        _storage = StorageService()
    return _storage
