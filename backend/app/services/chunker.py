"""切片器。

为什么自研而不直接用 LangChain 的 RecursiveCharacterTextSplitter：
1. 需要按中文标点（。！？；）定制分隔符优先级，默认的 "\n\n" 对中文文档切得太碎；
2. 需要 Markdown 标题感知（保留 section_path 供引用溯源）；
3. 需要保证表格不被切断（表格切一半，检索命中后模型无法理解）。
自研约 150 行，可控性远高于配置一个通用分割器。

注意：chunk_size 的单位是**字符数**，不是 token。
中文 1 字符 ≈ 1.6~1.8 token，所以 400 字符约等于 700 token。
"""

import re
from dataclasses import dataclass, field

from app.core.logging import get_logger

logger = get_logger(__name__)

# 表格行保护：切分前把表格内部的换行替换成占位符，避免被当成段落边界
TABLE_PLACEHOLDER = "\x00"
TABLE_ROW_RE = re.compile(r"^\s*\|.*\|\s*$")
HEADER_RE = re.compile(r"^(#{1,6})\s+(.+)$", re.M)

DEFAULT_SEPARATORS = ["\n\n", "\n", "。", "！", "？", "；", ". ", "; ", " "]


@dataclass
class ChunkConfig:
    strategy: str = "recursive"  # recursive | markdown_header | fixed
    chunk_size: int = 512
    chunk_overlap: int = 64
    # 只用来合并真正的碎片（如单个标题行）。设太大会把正常的小节吞进上一块，
    # 导致 section_path 归属错乱 —— 检索命中后引用会指向错误的章节。
    min_chunk_size: int = 30
    keep_table_intact: bool = True
    separators: list[str] = field(default_factory=lambda: list(DEFAULT_SEPARATORS))

    @classmethod
    def from_dict(cls, data: dict | None) -> "ChunkConfig":
        data = data or {}
        cfg = cls(
            strategy=data.get("strategy", "recursive"),
            chunk_size=int(data.get("chunk_size", 512)),
            chunk_overlap=int(data.get("chunk_overlap", 64)),
            min_chunk_size=int(data.get("min_chunk_size", 30)),
            keep_table_intact=bool(data.get("keep_table_intact", True)),
        )
        if isinstance(data.get("separators"), list) and data["separators"]:
            cfg.separators = [str(s) for s in data["separators"]]
        # 参数合法性兜底，避免后台配错导致切片爆炸
        if cfg.chunk_size < 100:
            cfg.chunk_size = 100
        if cfg.chunk_overlap >= cfg.chunk_size:
            cfg.chunk_overlap = cfg.chunk_size // 5
        return cfg

    def to_dict(self) -> dict:
        return {
            "strategy": self.strategy,
            "chunk_size": self.chunk_size,
            "chunk_overlap": self.chunk_overlap,
            "min_chunk_size": self.min_chunk_size,
            "keep_table_intact": self.keep_table_intact,
            "separators": self.separators,
        }


@dataclass
class ChunkDraft:
    content: str
    index: int
    section_path: str | None = None
    char_count: int = 0

    def __post_init__(self) -> None:
        self.char_count = len(self.content)


def _protect_tables(text: str) -> tuple[str, list[str]]:
    """把连续的 Markdown 表格行合并为一个不可分单元。"""
    lines = text.split("\n")
    out: list[str] = []
    tables: list[str] = []
    buf: list[str] = []

    for line in lines:
        if TABLE_ROW_RE.match(line):
            buf.append(line)
        else:
            if buf:
                tables.append(TABLE_PLACEHOLDER.join(buf))
                out.append(f"{TABLE_PLACEHOLDER}{len(tables) - 1}{TABLE_PLACEHOLDER}")
                buf = []
            out.append(line)
    if buf:
        tables.append(TABLE_PLACEHOLDER.join(buf))
        out.append(f"{TABLE_PLACEHOLDER}{len(tables) - 1}{TABLE_PLACEHOLDER}")

    return "\n".join(out), tables


def _restore_tables(text: str, tables: list[str]) -> str:
    def repl(m: re.Match) -> str:
        idx = int(m.group(1))
        return tables[idx].replace(TABLE_PLACEHOLDER, "\n") if idx < len(tables) else m.group(0)

    return re.sub(rf"{TABLE_PLACEHOLDER}(\d+){TABLE_PLACEHOLDER}", repl, text)


def _split_recursive(text: str, cfg: ChunkConfig, seps: list[str] | None = None) -> list[str]:
    """按分隔符优先级递归切分，再累积到接近 chunk_size 并加 overlap。"""
    seps = seps if seps is not None else cfg.separators
    text = text.strip()
    if not text:
        return []
    if len(text) <= cfg.chunk_size:
        return [text]

    # 选第一个能把文本切开的优先级分隔符
    sep = None
    for s in seps:
        if s and s in text:
            sep = s
            break

    if sep is None:
        # 没有可用分隔符，硬切
        step = max(cfg.chunk_size - cfg.chunk_overlap, 1)
        return [text[i : i + cfg.chunk_size] for i in range(0, len(text), step)]

    pieces = [p for p in text.split(sep) if p.strip()]
    chunks: list[str] = []
    buf = ""
    for p in pieces:
        candidate = f"{buf}{sep}{p}" if buf else p
        if len(candidate) <= cfg.chunk_size:
            buf = candidate
            continue
        if buf:
            chunks.append(buf.strip())
        if len(p) > cfg.chunk_size:
            # 单段仍超长，用下一级分隔符递归
            next_seps = seps[seps.index(sep) + 1 :] if sep in seps else []
            chunks.extend(_split_recursive(p, cfg, next_seps))
            buf = ""
        else:
            buf = p
    if buf.strip():
        chunks.append(buf.strip())

    # 加 overlap：从上一块尾部取一段拼到当前块前面，保证跨块语义连续
    if cfg.chunk_overlap > 0 and len(chunks) > 1:
        merged = [chunks[0]]
        for i in range(1, len(chunks)):
            prev_tail = chunks[i - 1][-cfg.chunk_overlap :]
            merged.append(f"{prev_tail}{chunks[i]}")
        chunks = merged

    return chunks


def _split_markdown_header(text: str, cfg: ChunkConfig) -> list[ChunkDraft]:
    """按 Markdown 标题层级切分，记录 section_path。"""
    matches = list(HEADER_RE.finditer(text))
    if not matches:
        return [
            ChunkDraft(content=c, index=i)
            for i, c in enumerate(_split_recursive(text, cfg))
        ]

    drafts: list[ChunkDraft] = []
    stack: list[tuple[int, str]] = []  # (level, title)

    # 第一个标题之前的内容
    if matches[0].start() > 0:
        head = text[: matches[0].start()].strip()
        if head:
            for c in _split_recursive(head, cfg):
                drafts.append(ChunkDraft(content=c, index=len(drafts)))

    for i, m in enumerate(matches):
        level = len(m.group(1))
        title = m.group(2).strip()
        # 维护标题栈，生成 "一级 > 二级" 路径
        while stack and stack[-1][0] >= level:
            stack.pop()
        stack.append((level, title))
        section_path = " > ".join(t for _, t in stack)

        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[m.end() : end].strip()
        if not body:
            continue

        for c in _split_recursive(body, cfg):
            drafts.append(
                ChunkDraft(content=c, index=len(drafts), section_path=section_path)
            )

    # 过短的碎片合并到前一块，而不是丢弃——
    # 直接丢弃会让"短小节"的内容永远检索不到，且不报错，属于静默数据丢失。
    merged: list[ChunkDraft] = []
    for d in drafts:
        if d.char_count < cfg.min_chunk_size and merged:
            prev = merged[-1]
            prev.content = f"{prev.content}\n{d.content}"
            prev.char_count = len(prev.content)
            # 跨章节合并后原 section_path 不再准确，退到父级，避免引用指错章节
            if prev.section_path and d.section_path and prev.section_path != d.section_path:
                prev.section_path = (
                    prev.section_path.rsplit(" > ", 1)[0]
                    if " > " in prev.section_path
                    else None
                )
        else:
            merged.append(d)

    for i, d in enumerate(merged):
        d.index = i
    return merged


def split_text(text: str, cfg: ChunkConfig | None = None) -> list[ChunkDraft]:
    cfg = cfg or ChunkConfig()
    if not text or not text.strip():
        return []

    tables: list[str] = []
    work = text
    if cfg.keep_table_intact:
        work, tables = _protect_tables(text)

    if cfg.strategy == "markdown_header":
        drafts = _split_markdown_header(work, cfg)
    elif cfg.strategy == "fixed":
        step = max(cfg.chunk_size - cfg.chunk_overlap, 1)
        drafts = [
            ChunkDraft(content=work[i : i + cfg.chunk_size], index=n)
            for n, i in enumerate(range(0, len(work), step))
            if work[i : i + cfg.chunk_size].strip()
        ]
    else:  # recursive
        drafts = [
            ChunkDraft(content=c, index=i)
            for i, c in enumerate(_split_recursive(work, cfg))
        ]

    if tables:
        for d in drafts:
            d.content = _restore_tables(d.content, tables)
            d.char_count = len(d.content)

    logger.info(
        "split_done",
        strategy=cfg.strategy,
        chunks=len(drafts),
        chars=sum(d.char_count for d in drafts),
        avg=round(sum(d.char_count for d in drafts) / max(len(drafts), 1)),
    )
    return drafts
