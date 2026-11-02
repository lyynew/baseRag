"""文档解析：统一输出 Markdown。

为什么要统一成 Markdown：
后续切片器只需要处理一种格式，且标题层级（#）和表格（|）能直接用于结构化切片，
不需要为每种文件类型写一套切片逻辑。

关于扫描件（重要）：
不做 OCR 时，扫描版 PDF 不会报错，只会安静地产生 0 字符。用户会以为上传成功，
直到提问时才发现搜不到。所以这里必须**主动检测文本层并抛 NO_TEXT_LAYER**。
"""

from dataclasses import dataclass, field
from pathlib import Path

from app.core.errors import AppError, ErrorCode
from app.core.logging import get_logger

logger = get_logger(__name__)

# 文本层判定阈值：正文字符数低于此值视为无文本层（纯图片 PDF）
MIN_TEXT_CHARS = 30
# 平均每页字符数低于此值，也判定为扫描件（有些 PDF 只有页眉文字）
MIN_CHARS_PER_PAGE = 20
# docx 的 XML 命名空间
W_NAMESPACE = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


@dataclass
class ParsedDoc:
    text: str
    page_count: int = 1
    char_count: int = 0
    no_text_layer: bool = False
    meta: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.char_count:
            self.char_count = len(self.text)


def _rows_to_markdown(rows: list[list[str]]) -> str:
    """二维数据转 Markdown 表格，跳过全空行。"""
    cleaned = [[str(c).strip() if c is not None else "" for c in r] for r in rows]
    cleaned = [r for r in cleaned if any(r)]
    if not cleaned:
        return ""
    width = max(len(r) for r in cleaned)
    cleaned = [r + [""] * (width - len(r)) for r in cleaned]
    header = "| " + " | ".join(cleaned[0]) + " |"
    sep = "| " + " | ".join(["---"] * width) + " |"
    body = ["| " + " | ".join(r) + " |" for r in cleaned[1:]]
    return "\n".join([header, sep, *body])


# ---------------- 各类型解析器 ----------------
def _parse_pdf(path: Path) -> ParsedDoc:
    # PyMuPDF 2.x 起包名改为 pymupdf，旧的 `import fitz` 会发 FutureWarning
    import pymupdf

    parts: list[str] = []
    page_texts: list[str] = []
    table_count = 0

    with pymupdf.open(path) as doc:
        page_count = doc.page_count
        for page_no in range(page_count):
            page = doc.load_page(page_no)
            text = page.get_text("text").strip()

            # 表格单独提取，转成 Markdown 保留结构
            try:
                found = page.find_tables()
                for tb in found.tables:
                    md = _rows_to_markdown(tb.extract())
                    if md:
                        text += f"\n\n{md}\n"
                        table_count += 1
            except Exception:  # noqa: BLE001  表格识别失败不影响正文
                pass

            if text:
                # 每页加页标记，便于引用溯源
                parts.append(f"<!-- page:{page_no + 1} -->\n{text}")
                page_texts.append(text)

    full = "\n\n".join(parts)
    total_chars = sum(len(t) for t in page_texts)
    no_text = total_chars < MIN_TEXT_CHARS or (
        page_texts and total_chars / max(len(page_texts), 1) < MIN_CHARS_PER_PAGE
    )
    return ParsedDoc(
        text=full,
        page_count=page_count,
        char_count=total_chars,
        no_text_layer=bool(no_text),
        meta={"tables": table_count, "pages_with_text": len(page_texts)},
    )


def _parse_docx(path: Path) -> ParsedDoc:
    from docx import Document

    doc = Document(str(path))
    lines: list[str] = []

    # 按文档顺序遍历段落与表格
    for block in doc.element.body.iterchildren():
        tag = block.tag.split("}")[-1]
        if tag == "p":
            text = "".join(node.text or "" for node in block.iter() if node.tag.endswith("}t"))
            text = text.strip()
            if not text:
                continue
            # 用样式判断标题
            style_name = ""
            for node in block.iter():
                if node.tag.endswith("}pStyle"):
                    style_name = node.get(f"{W_NAMESPACE}val") or ""
                    break
            if style_name.lower().startswith("heading") or style_name.startswith("标题"):
                level = "".join(ch for ch in style_name if ch.isdigit()) or "1"
                level = min(int(level), 6)
                lines.append(f"{'#' * level} {text}")
            else:
                lines.append(text)
        elif tag == "tbl":
            try:
                rows = []
                for tr in block.iter():
                    if not tr.tag.endswith("}tr"):
                        continue
                    cells = []
                    for tc in tr.iter():
                        if tc.tag.endswith("}tc"):
                            cells.append(
                                "".join(
                                    n.text or "" for n in tc.iter() if n.tag.endswith("}t")
                                )
                            )
                    if cells:
                        rows.append(cells)
                md = _rows_to_markdown(rows)
                if md:
                    lines.append(md)
            except Exception:  # noqa: BLE001
                pass

    full = "\n\n".join(lines)
    return ParsedDoc(text=full, page_count=1, char_count=len(full))


def _parse_text(path: Path) -> ParsedDoc:
    raw = path.read_text(encoding="utf-8", errors="ignore")
    return ParsedDoc(text=raw, page_count=1, char_count=len(raw))


def _parse_xlsx(path: Path) -> ParsedDoc:
    from openpyxl import load_workbook

    wb = load_workbook(str(path), read_only=True, data_only=True)
    parts: list[str] = []
    for sheet in wb.worksheets:
        rows = [[c for c in row] for row in sheet.iter_rows(values_only=True)]
        md = _rows_to_markdown(rows)
        if md:
            parts.append(f"## {sheet.title}\n\n{md}")
    wb.close()
    full = "\n\n".join(parts)
    return ParsedDoc(text=full, page_count=len(wb.worksheets), char_count=len(full))


def _parse_csv(path: Path) -> ParsedDoc:
    import csv

    with path.open("r", encoding="utf-8", errors="ignore", newline="") as f:
        rows = list(csv.reader(f))
    md = _rows_to_markdown(rows)
    return ParsedDoc(text=md, page_count=1, char_count=len(md))


# 策略注册表：新增格式只需在此登记，不动调用方
PARSERS = {
    "pdf": _parse_pdf,
    "docx": _parse_docx,
    "doc": _parse_docx,  # .doc 实际无法用 python-docx 解析，见下方校验
    "md": _parse_text,
    "markdown": _parse_text,
    "txt": _parse_text,
    "xlsx": _parse_xlsx,
    "xls": _parse_xlsx,
    "csv": _parse_csv,
}


def parse_document(path: Path, ext: str) -> ParsedDoc:
    ext = ext.lower().lstrip(".")
    parser = PARSERS.get(ext)
    if parser is None:
        raise AppError(
            f"不支持的文件类型：.{ext}",
            code=ErrorCode.UNSUPPORTED_FILE_TYPE,
            status_code=415,
        )

    if ext == "doc":
        raise AppError(
            "不支持旧版 .doc 格式，请另存为 .docx 后重新上传",
            code=ErrorCode.UNSUPPORTED_FILE_TYPE,
            status_code=415,
        )

    try:
        result = parser(path)
    except AppError:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.exception("parse_failed", ext=ext, error=str(exc))
        raise AppError(
            f"文档解析失败：{type(exc).__name__}: {exc}",
            code=ErrorCode.PARSE_FAILED,
            status_code=422,
        ) from exc

    if result.no_text_layer or result.char_count < MIN_TEXT_CHARS:
        raise AppError(
            "该文件没有可提取的文本层（可能是扫描件或纯图片），"
            "当前版本不支持 OCR，请上传可复制文字的版本",
            code=ErrorCode.NO_TEXT_LAYER,
            status_code=422,
            detail={
                "page_count": result.page_count,
                "char_count": result.char_count,
            },
        )

    logger.info(
        "parse_ok",
        ext=ext,
        chars=result.char_count,
        pages=result.page_count,
        tables=result.meta.get("tables", 0),
    )
    return result
