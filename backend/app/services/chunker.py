"""切片器：块级保护 + 句子边界对齐 + 自定义标记。

为什么自研而不是用 LangChain 的 RecursiveCharacterTextSplitter：
1. 中文需要按「。！？；」切句，默认分隔符会把中文切碎；
2. 需要 Markdown 标题感知，保留 section_path 供引用溯源；
3. 需要保护结构块（代码、表格、列表、引用），通用分割器不认识这些。

三条硬约束（都是踩过坑才加的）：

**约束一：代码块不能被切开。**
```` ```  出现奇数次的切片，渲染出来是破的；两半都不可读，检索命中反而误导模型。
所以代码块整体作为一个原子单元；超过上限时按行切，**每片都补回围栏和语言标记**。

**约束二：表格切开必须补表头。**
只保留数据行、没有表头的那半截表格，模型看到的是"一堆 | a | b |"，无法理解含义。

**约束三：不在句子中间切断。**
硬切时先回退到最近的句末标点或换行。这一点最影响检索质量：
"ref 需要写 .value" 被切成 "ref 需要写 .val" + "ue"，两块都无法命中。

chunk_size 单位是**字符**不是 token。中文 1 字符 ≈ 1.6~1.8 token。
"""

import re
from dataclasses import dataclass, field

from app.core.logging import get_logger

logger = get_logger(__name__)

# ---------------- 正则 ----------------
HEADER_RE = re.compile(r"^(#{1,6})\s+(.+)$", re.M)
TABLE_ROW_RE = re.compile(r"^\s*\|.*\|\s*$")
FENCE_RE = re.compile(r"^(\s*)(`{3,}|~{3,})\s*([A-Za-z0-9_+-]*)\s*$")
LIST_ITEM_RE = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+")
QUOTE_RE = re.compile(r"^\s*>\s?")
# 独占一行的加粗文本，当作伪标题（真实文档里极常见：**1. xxx**）
BOLD_HEADING_RE = re.compile(r"^\*\*[^*\n]{1,60}\*\*[：:]?$")

# 句末标点：切分时优先在这里断开
SENT_END_CHARS = "。！？；.!?;"
# 次级断点：句子内部较自然的停顿
SOFT_BREAK_CHARS = "，,、：: \n\t"

DEFAULT_SEPARATORS = ["\n\n", "\n", "。", "！", "？", "；", ". ", "; ", " "]


@dataclass
class ChunkConfig:
    # recursive | markdown_header | fixed | delimiter
    strategy: str = "recursive"
    chunk_size: int = 512
    chunk_overlap: int = 64
    # 只合并真正的碎片（如孤立标题行）。设太大会把正常小节吞进上一块，
    # 导致 section_path 归属错乱 —— 检索命中后引用会指向错误的章节。
    min_chunk_size: int = 30

    keep_table_intact: bool = True
    keep_code_intact: bool = True
    keep_list_intact: bool = True
    keep_quote_intact: bool = True

    # 结构块允许超出 chunk_size 的倍数。代码/表格被切碎的代价远高于略超长度，
    # 所以给到 2 倍容忍度；超过才真正内部分片。
    block_max_ratio: float = 2.0

    # 自定义标记策略专用
    delimiter: str = ""
    keep_delimiter: bool = True

    # 是否把标题注入每个切片开头。切片脱离文档后，"要求：1. 只使用资料中的信息"
    # 没有标题就不知道是谁的要求，检索和生成都会吃亏。
    keep_heading: bool = True

    # 是否合并相邻小块（缓解原子块独占带来的碎片化）
    merge_adjacent: bool = True

    separators: list[str] = field(default_factory=lambda: list(DEFAULT_SEPARATORS))

    @classmethod
    def from_dict(cls, data: dict | None) -> "ChunkConfig":
        data = data or {}
        strategy = str(data.get("strategy", "recursive"))
        if strategy not in ("recursive", "markdown_header", "fixed", "delimiter"):
            strategy = "recursive"
        cfg = cls(
            strategy=strategy,
            chunk_size=int(data.get("chunk_size", 512)),
            chunk_overlap=int(data.get("chunk_overlap", 64)),
            min_chunk_size=int(data.get("min_chunk_size", 30)),
            keep_table_intact=bool(data.get("keep_table_intact", True)),
            keep_code_intact=bool(data.get("keep_code_intact", True)),
            keep_list_intact=bool(data.get("keep_list_intact", True)),
            keep_quote_intact=bool(data.get("keep_quote_intact", True)),
            block_max_ratio=float(data.get("block_max_ratio", 2.0)),
            delimiter=str(data.get("delimiter") or ""),
            keep_delimiter=bool(data.get("keep_delimiter", True)),
        )
        if isinstance(data.get("separators"), list) and data["separators"]:
            cfg.separators = [str(s) for s in data["separators"]]
        # 参数合法性兜底，避免后台配错导致切片爆炸
        if cfg.chunk_size < 100:
            cfg.chunk_size = 100
        if cfg.chunk_overlap >= cfg.chunk_size:
            cfg.chunk_overlap = cfg.chunk_size // 5
        if cfg.min_chunk_size >= cfg.chunk_size:
            cfg.min_chunk_size = cfg.chunk_size // 8
        if cfg.block_max_ratio < 1.0:
            cfg.block_max_ratio = 2.0
        return cfg

    def to_dict(self) -> dict:
        return {
            "strategy": self.strategy,
            "chunk_size": self.chunk_size,
            "chunk_overlap": self.chunk_overlap,
            "min_chunk_size": self.min_chunk_size,
            "keep_table_intact": self.keep_table_intact,
            "keep_code_intact": self.keep_code_intact,
            "keep_list_intact": self.keep_list_intact,
            "keep_quote_intact": self.keep_quote_intact,
            "block_max_ratio": self.block_max_ratio,
            "delimiter": self.delimiter,
            "keep_delimiter": self.keep_delimiter,
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


@dataclass
class Block:
    """不可分割的结构块。"""

    kind: str  # code | table | list | quote
    text: str
    fence: str = "```"
    lang: str = ""


# ---------------- 块提取 ----------------
def _extract_blocks(text: str, cfg: ChunkConfig) -> list[tuple[str, object]]:
    """把正文拆成 [("text", str) | ("block", Block)] 交替序列。

    顺序很关键：必须先识别代码块再识别表格。
    代码里出现 `` | a | b | `` 这种内容是常见的（SQL、Markdown 示例），
    先认表格会把代码劈成两半。
    """
    lines = text.split("\n")
    segs: list[tuple[str, object]] = []
    buf: list[str] = []
    i = 0

    def flush_text() -> None:
        if buf:
            joined = "\n".join(buf).strip()
            if joined:
                segs.append(("text", joined))
            buf.clear()

    while i < len(lines):
        line = lines[i]
        fence_m = FENCE_RE.match(line)

        # ---- 代码块 ----
        if fence_m and cfg.keep_code_intact:
            flush_text()
            fence, lang = fence_m.group(2), fence_m.group(3)
            collected = [line]
            i += 1
            closed = False
            while i < len(lines):
                current = lines[i]
                m2 = FENCE_RE.match(current)
                collected.append(current)
                i += 1
                # 闭合围栏：同种字符、长度不短于开启标记、且无语言标记
                if (
                    m2
                    and m2.group(2)[0] == fence[0]
                    and len(m2.group(2)) >= len(fence)
                    and not m2.group(3)
                ):
                    closed = True
                    break
            if not closed:
                # 文档里围栏没闭合（手写文档常见）：补一个，避免切开后两半都破
                collected.append(fence)
                logger.warning("code_fence_unclosed", lang=lang)
            segs.append(
                ("block", Block(kind="code", text="\n".join(collected), fence=fence, lang=lang))
            )
            continue

        # ---- 表格 ----
        if cfg.keep_table_intact and TABLE_ROW_RE.match(line):
            flush_text()
            collected = []
            while i < len(lines) and TABLE_ROW_RE.match(lines[i]):
                collected.append(lines[i])
                i += 1
            # 单行不算表格（可能只是正文里的 | 符号）
            if len(collected) >= 2:
                segs.append(("block", Block(kind="table", text="\n".join(collected))))
            else:
                buf.extend(collected)
            continue

        # ---- 引用块 ----
        if cfg.keep_quote_intact and QUOTE_RE.match(line):
            flush_text()
            collected = []
            while i < len(lines) and QUOTE_RE.match(lines[i]):
                collected.append(lines[i])
                i += 1
            segs.append(("block", Block(kind="quote", text="\n".join(collected))))
            continue

        # ---- 列表块（连续列表项 + 其缩进续行）----
        if cfg.keep_list_intact and LIST_ITEM_RE.match(line):
            flush_text()
            collected = [line]
            i += 1
            while i < len(lines):
                nxt = lines[i]
                if LIST_ITEM_RE.match(nxt) or (nxt.startswith((" ", "\t")) and nxt.strip()):
                    collected.append(nxt)
                    i += 1
                    continue
                # 空行后紧跟列表项，视为同一列表
                if not nxt.strip() and i + 1 < len(lines) and LIST_ITEM_RE.match(lines[i + 1]):
                    collected.append(nxt)
                    i += 1
                    continue
                break
            segs.append(("block", Block(kind="list", text="\n".join(collected).rstrip())))
            continue

        buf.append(line)
        i += 1

    flush_text()
    return segs


# ---------------- 块内部分片 ----------------
def _split_code(block: Block, cfg: ChunkConfig) -> list[str]:
    """超长代码按行切，每片都补回围栏与语言标记，保证每片都可读。"""
    lines = block.text.split("\n")
    body = lines[1:-1] if len(lines) >= 2 else lines[1:]
    overhead = len(block.fence) * 2 + len(block.lang) + 4
    budget = max(cfg.chunk_size - overhead, 120)

    out: list[str] = []
    buf: list[str] = []
    size = 0
    for line in body:
        if size + len(line) + 1 > budget and buf:
            out.append(f"{block.fence}{block.lang}\n" + "\n".join(buf) + f"\n{block.fence}")
            buf, size = [], 0
        buf.append(line)
        size += len(line) + 1
    if buf:
        out.append(f"{block.fence}{block.lang}\n" + "\n".join(buf) + f"\n{block.fence}")
    return out or [block.text]


def _split_table(block: Block, cfg: ChunkConfig) -> list[str]:
    """超长表格按行切，每片都重复表头——没有表头的数据行模型无法理解。"""
    rows = [r for r in block.text.split("\n") if r.strip()]
    if len(rows) <= 2:
        return [block.text]
    head = rows[:2]
    head_text = "\n".join(head)
    budget = max(cfg.chunk_size - len(head_text) - 1, 100)

    out: list[str] = []
    buf: list[str] = []
    size = 0
    for row in rows[2:]:
        if size + len(row) + 1 > budget and buf:
            out.append(head_text + "\n" + "\n".join(buf))
            buf, size = [], 0
        buf.append(row)
        size += len(row) + 1
    if buf:
        out.append(head_text + "\n" + "\n".join(buf))
    return out


def _split_list(block: Block, cfg: ChunkConfig) -> list[str]:
    """超长列表按项切，每项自带前缀，天然完整。"""
    items: list[list[str]] = []
    for line in block.text.split("\n"):
        if LIST_ITEM_RE.match(line) or not items:
            items.append([line])
        else:
            items[-1].append(line)

    out: list[str] = []
    buf: list[str] = []
    size = 0
    for item in items:
        text = "\n".join(item)
        if size + len(text) + 1 > cfg.chunk_size and buf:
            out.append("\n".join(buf))
            buf, size = [], 0
        buf.append(text)
        size += len(text) + 1
    if buf:
        out.append("\n".join(buf))
    return out


def _split_block(block: Block, cfg: ChunkConfig) -> list[str]:
    """结构块：不超阈值就整块保留，超了才按类型内部分片。"""
    if len(block.text) <= cfg.chunk_size * cfg.block_max_ratio:
        return [block.text]
    if block.kind == "code":
        return _split_code(block, cfg)
    if block.kind == "table":
        return _split_table(block, cfg)
    if block.kind == "list":
        return _split_list(block, cfg)
    return _hard_split(block.text, cfg)


# ---------------- 文本分片 ----------------
def _find_cut(window: str, min_ratio: float = 0.6) -> int:
    """在窗口内从后往前找最自然的断点，返回断点下标（含）。

    优先句末标点 → 次级停顿（逗号、空格）→ 找不到就硬切。
    加 min_ratio 是为了避免"切得太早"，把每块都切成很短。
    """
    threshold = int(len(window) * min_ratio)
    for chars in (SENT_END_CHARS, SOFT_BREAK_CHARS):
        for pos in range(len(window) - 1, threshold - 1, -1):
            if window[pos] in chars:
                return pos
    return -1


def _hard_split(text: str, cfg: ChunkConfig) -> list[str]:
    """兜底硬切：先对齐到标点，实在没有才按字符截断。"""
    out: list[str] = []
    rest = text.strip()
    while rest:
        if len(rest) <= cfg.chunk_size:
            out.append(rest)
            break
        window = rest[: cfg.chunk_size]
        cut = _find_cut(window)
        end = cut + 1 if cut >= 0 else cfg.chunk_size
        piece = rest[:end].strip()
        if piece:
            out.append(piece)
        rest = rest[end:].lstrip()
    return out


def _split_paragraph(para: str, cfg: ChunkConfig) -> list[str]:
    """单段超长：先按行，再按句，最后硬切。"""
    units: list[str] = []
    buf = ""
    for line in para.split("\n"):
        candidate = f"{buf}\n{line}" if buf else line
        if len(candidate) <= cfg.chunk_size:
            buf = candidate
            continue
        if buf.strip():
            units.append(buf.strip())
        buf = ""
        if len(line) <= cfg.chunk_size:
            buf = line
        else:
            units.extend(_hard_split(line, cfg))
    if buf.strip():
        units.append(buf.strip())
    return units


def _atomic_units(text: str, cfg: ChunkConfig) -> list[str]:
    """把纯文本拆成不超过 chunk_size 的语义单元，供上层累积。"""
    text = text.strip()
    if not text:
        return []
    if len(text) <= cfg.chunk_size:
        return [text]

    units: list[str] = []
    for para in re.split(r"\n{2,}", text):
        para = para.strip()
        if not para:
            continue
        if len(para) <= cfg.chunk_size:
            units.append(para)
        else:
            units.extend(_split_paragraph(para, cfg))
    return units


def _is_structured(chunk: str) -> bool:
    """是否是结构块（代码/表格）。这类块之间不加 overlap，加了反而污染。"""
    if "```" in chunk or "~~~" in chunk:
        return True
    table_lines = sum(1 for line in chunk.split("\n") if TABLE_ROW_RE.match(line))
    return table_lines >= 2


def _tail_overlap(prev: str, limit: int) -> str:
    """取上一块尾部用于 overlap，尽量从完整句子开始。"""
    if limit <= 0 or len(prev) <= limit:
        return prev
    tail = prev[-limit:]
    # 找 tail 里第一个句末标点，取其后 —— 避免下一块以半句话开头
    for i, ch in enumerate(tail):
        if ch in SENT_END_CHARS or ch == "\n":
            return tail[i + 1 :].lstrip()
    return tail


def _apply_overlap(chunks: list[str], cfg: ChunkConfig) -> list[str]:
    if cfg.chunk_overlap <= 0 or len(chunks) < 2:
        return chunks

    out = [chunks[0]]
    for i in range(1, len(chunks)):
        prev, cur = chunks[i - 1], chunks[i]
        if _is_structured(prev) or _is_structured(cur):
            out.append(cur)
            continue
        tail = _tail_overlap(prev, cfg.chunk_overlap)
        # 重叠后不能超过 chunk_size 太多，否则会把块撑爆
        if tail and len(tail) + len(cur) <= cfg.chunk_size * 1.2:
            out.append(f"{tail}\n{cur}")
        else:
            out.append(cur)
    return out


def _rebind_tail_headings(chunks: list[str]) -> list[str]:
    """把落在块尾的标题行移到下一块开头。

    两类来源：
    1. 真实文档大量用 ``**1. 命名路由跳转时 params 丢失**`` 这种加粗行代替标题层级；
    2. recursive 不感知标题，下一节的 ``## xxx`` 会混在文本流里恰好落在块尾。

    不处理的话：上一块"有标题没内容"、下一块"有内容没标题"，两边都失去上下文。
    这是纯指标看不出来、但检索效果会明显下降的问题。
    """
    if len(chunks) < 2:
        return chunks

    for i in range(len(chunks) - 1):
        lines = chunks[i].rstrip().split("\n")
        if len(lines) < 2:
            continue
        last = lines[-1].strip()
        if BOLD_HEADING_RE.match(last) or _is_lone_heading(last):
            chunks[i] = "\n".join(lines[:-1]).rstrip()
            chunks[i + 1] = f"{last}\n\n{chunks[i + 1]}"
    return [c for c in chunks if c.strip()]


def _is_lone_heading(text: str) -> bool:
    """整块只是一个标题行。这种块无论多长都该附着到内容上——
    长标题（如 "# Vue Router 4 使用要点"）超过 min_chunk_size，
    用长度判断会漏掉，表现为"块尾是标题"的垃圾块。"""
    s = text.strip()
    return bool(s) and "\n" not in s and s.startswith("#")


def _merge_tiny_forward(chunks: list[str], cfg: ChunkConfig) -> list[str]:
    """recursive 策略专用：短块向后附着。

    recursive 不感知标题，"## 要点" 这种标题行会单独成块。
    它应该附着到后面的内容上，而不是留成一个谁也检索不到的孤儿块。
    与 markdown_header 的向前合并方向相反：这里的短块几乎总是标题，
    标题属于它**后面**的内容。
    """
    if cfg.min_chunk_size <= 0 or len(chunks) < 2:
        return chunks

    out: list[str] = []
    i = 0
    while i < len(chunks):
        cur = chunks[i]
        should_attach = _is_lone_heading(cur) or len(cur) < cfg.min_chunk_size
        if should_attach and i + 1 < len(chunks):
            chunks[i + 1] = f"{cur}\n\n{chunks[i + 1]}"
        else:
            out.append(cur)
        i += 1
    return out


def _merge_adjacent(chunks: list[str], cfg: ChunkConfig) -> list[str]:
    """把相邻的小块合并，避免"标题 + 一小段代码"单独成块。

    原子块独占是为了保住结构，但代价是碎片化：一段 60 字的说明 + 一个 90 字的代码块
    会被切成两块，两块各自信息量都不足，嵌入向量区分度低。这里做一轮贪心合并，
    上限放宽到 chunk_size * 1.1（略超比切碎更好）。

    只在同一 section 内部调用，不会跨主题合并。
    """
    if not cfg.merge_adjacent or len(chunks) < 2:
        return chunks

    limit = cfg.chunk_size * 1.1
    out: list[str] = []
    for c in chunks:
        if out and len(out[-1]) + len(c) + 2 <= limit:
            out[-1] = f"{out[-1]}\n\n{c}"
        else:
            out.append(c)
    return out


def _split_body(
    body: str, cfg: ChunkConfig, *, merge_tiny_forward: bool = False
) -> list[str]:
    """正文分片主流程：文本段累积 + 结构块独占。

    merge_tiny_forward：recursive 策略用。它不感知标题，孤立标题行会单独成块，
    需要"向后附着"到内容上；markdown_header 有自己的向前合并，不能用这个。
    """
    if not body.strip():
        return []
    segs = _extract_blocks(body, cfg)
    if not segs:
        return []

    def _finish(parts: list[str]) -> list[str]:
        parts = _merge_adjacent(parts, cfg)
        if merge_tiny_forward:
            parts = _merge_tiny_forward(parts, cfg)
        return _apply_overlap(_rebind_tail_headings(parts), cfg)

    # 全是文本，走轻量路径
    if len(segs) == 1 and segs[0][0] == "text":
        chunks: list[str] = []
        buf = ""
        for unit in _atomic_units(str(segs[0][1]), cfg):
            candidate = f"{buf}\n\n{unit}" if buf else unit
            if len(candidate) <= cfg.chunk_size:
                buf = candidate
            else:
                if buf:
                    chunks.append(buf)
                buf = unit
        if buf:
            chunks.append(buf)
        return _finish(chunks)

    chunks = []
    buf = ""

    def flush() -> None:
        nonlocal buf
        if buf.strip():
            chunks.append(buf.strip())
        buf = ""

    for kind, payload in segs:
        if kind == "text":
            for unit in _atomic_units(str(payload), cfg):
                candidate = f"{buf}\n\n{unit}" if buf else unit
                if len(candidate) <= cfg.chunk_size:
                    buf = candidate
                else:
                    flush()
                    buf = unit
        else:
            block = payload
            assert isinstance(block, Block)
            # 小块可以跟前面的文字同块；大块独占
            if buf and len(buf) + len(block.text) + 2 <= cfg.chunk_size:
                buf = f"{buf}\n\n{block.text}"
            else:
                # 短文本（通常是标题）+ 超长块：标题附着到分片后的第一块，
                # 否则 "## 安装与基础配置" + 500 字代码会切出"只有标题没有内容"的块
                carry = buf.strip() if buf and len(buf.strip()) < cfg.min_chunk_size else ""
                flush()
                pieces = _split_block(block, cfg)
                if carry and pieces:
                    pieces[0] = f"{carry}\n\n{pieces[0]}"
                chunks.extend(pieces)
    flush()
    return _finish(chunks)


# ---------------- 策略 ----------------
def _split_markdown_header(text: str, cfg: ChunkConfig) -> list[ChunkDraft]:
    """按标题层级切分，每个 section 内部再做块级分片，记录 section_path。"""
    matches = list(HEADER_RE.finditer(text))
    if not matches:
        return [ChunkDraft(content=c, index=i) for i, c in enumerate(_split_body(text, cfg))]

    drafts: list[ChunkDraft] = []
    stack: list[tuple[int, str]] = []

    if matches[0].start() > 0:
        head = text[: matches[0].start()].strip()
        for c in _split_body(head, cfg):
            drafts.append(ChunkDraft(content=c, index=len(drafts)))

    for i, m in enumerate(matches):
        level = len(m.group(1))
        title = m.group(2).strip()
        while stack and stack[-1][0] >= level:
            stack.pop()
        stack.append((level, title))
        # 标题也放进正文前缀，否则切片脱离标题后语义不明（"要求：1.xxx" 不知道是谁的要求）
        section_path = " > ".join(t for _, t in stack)
        heading = f"{m.group(1)} {title}"

        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[m.end() : end].strip()
        if not body:
            continue

        for c in _split_body(body, cfg):
            content = f"{heading}\n\n{c}" if cfg.keep_heading else c
            drafts.append(
                ChunkDraft(content=content, index=len(drafts), section_path=section_path)
            )

    # 过短碎片合并到前一块，但不允许合并后超过上限
    merged: list[ChunkDraft] = []
    for d in drafts:
        prev = merged[-1] if merged else None
        can_merge = (
            prev is not None
            and d.char_count < cfg.min_chunk_size
            and len(prev.content) + d.char_count + 1 <= cfg.chunk_size * 1.2
        )
        if can_merge:
            prev.content = f"{prev.content}\n{d.content}"
            prev.char_count = len(prev.content)
            # 跨章节合并后原 section_path 不再准确，退到父级，避免引用指错章节
            if prev.section_path and d.section_path and prev.section_path != d.section_path:
                prev.section_path = (
                    prev.section_path.rsplit(" > ", 1)[0] if " > " in prev.section_path else None
                )
        else:
            merged.append(d)

    for i, d in enumerate(merged):
        d.index = i
    return merged


def _split_by_delimiter(text: str, cfg: ChunkConfig) -> list[ChunkDraft]:
    """严格按自定义标记切分。

    与其它策略的区别：**不做语义合并**。用户既然指定了边界，就说明这个边界
    对业务有意义（如 `<!-- chunk -->`、`## `、`---`），合并会破坏这个约定。
    只对单段超长的部分做内部分片。

    标记按**行首**锚定，而不是无脑字符串切分。原因：`## ` 是 `### ` 的前缀，
    字符串切分会把三级标题劈成 "# " 开头的碎块——这是 delimiter 策略
    最容易踩的坑，而且切完的碎片看起来"像是切过"，很难意识到是规则错了。
    行首锚定后 `## ` 只匹配二级标题行。
    """
    if not cfg.delimiter:
        logger.warning("delimiter_missing_fallback", fallback="markdown_header")
        return _split_markdown_header(text, cfg)

    pattern = rf"(?m)^\s*{re.escape(cfg.delimiter)}"
    parts = re.split(pattern, text)
    drafts: list[ChunkDraft] = []
    for i, part in enumerate(parts):
        part = part.strip()
        if not part:
            continue
        content = f"{cfg.delimiter}{part}" if (i > 0 and cfg.keep_delimiter) else part
        pieces = (
            _split_body(content, cfg) if len(content) > cfg.chunk_size * 1.2 else [content]
        )
        for piece in pieces:
            drafts.append(ChunkDraft(content=piece, index=len(drafts)))

    for i, d in enumerate(drafts):
        d.index = i

    # 标记之间的孤立标题附着到下一块。
    # 注意只附着**标题行**：delimiter 模式下用户用标记划出的短段落本身就是边界，
    # 合并它们等于推翻用户的切分意图。只有孤零零的标题（如文档开头的大标题）
    # 留在原地才会产生检索不到、也读不懂的垃圾块。
    return _merge_tiny_drafts(drafts, cfg, only_headings=True)


def _merge_tiny_drafts(
    drafts: list[ChunkDraft], cfg: ChunkConfig, *, only_headings: bool = False
) -> list[ChunkDraft]:
    if cfg.min_chunk_size <= 0 or len(drafts) < 2:
        return drafts

    def _is_tiny(d: ChunkDraft) -> bool:
        if only_headings:
            return _is_lone_heading(d.content)
        return d.char_count < cfg.min_chunk_size

    out: list[ChunkDraft] = []
    i = 0
    while i < len(drafts):
        d = drafts[i]
        if _is_tiny(d) and i + 1 < len(drafts):
            nxt = drafts[i + 1]
            drafts[i + 1] = ChunkDraft(
                content=f"{d.content}\n\n{nxt.content}",
                index=nxt.index,
                section_path=nxt.section_path or d.section_path,
            )
        else:
            out.append(d)
        i += 1
    for j, d in enumerate(out):
        d.index = j
    return out


def split_text(
    text: str, cfg: ChunkConfig | None = None, *, keep_heading: bool = True
) -> list[ChunkDraft]:
    cfg = cfg or ChunkConfig()
    if not text or not text.strip():
        return []
    if not keep_heading:
        cfg.keep_heading = False

    if cfg.strategy == "delimiter":
        drafts = _split_by_delimiter(text, cfg)
    elif cfg.strategy == "markdown_header":
        drafts = _split_markdown_header(text, cfg)
    elif cfg.strategy == "fixed":
        step = max(cfg.chunk_size - cfg.chunk_overlap, 1)
        drafts = [
            ChunkDraft(content=text[i : i + cfg.chunk_size], index=n)
            for n, i in enumerate(range(0, len(text), step))
            if text[i : i + cfg.chunk_size].strip()
        ]
    else:  # recursive
        drafts = [
            ChunkDraft(content=c, index=i)
            for i, c in enumerate(_split_body(text, cfg, merge_tiny_forward=True))
        ]

    stats = validate_chunks(drafts, cfg.chunk_size)
    logger.info(
        "split_done",
        strategy=cfg.strategy,
        chunks=len(drafts),
        chars=sum(d.char_count for d in drafts),
        avg=round(sum(d.char_count for d in drafts) / max(len(drafts), 1)),
        broken_code=stats["broken_code"],
    )
    return drafts


def validate_chunks(drafts: list[ChunkDraft], max_size: int = 0) -> dict:
    """切完自检。代码块未闭合是硬伤，记 warning 便于在生产日志里发现。

    不抛异常：切片有瑕疵也要能入库，只是质量差；
    但必须留下痕迹，否则"检索效果变差"永远查不到原因。
    """
    broken = 0
    over = 0
    for d in drafts:
        if d.content.count("```") % 2 == 1 or d.content.count("~~~") % 2 == 1:
            broken += 1
            logger.warning("chunk_code_block_broken", index=d.index, tail=d.content[-40:])
        if max_size and d.char_count > max_size * 2:
            over += 1
    return {"broken_code": broken, "over_size": over}
