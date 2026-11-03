"""切片器单元测试。

这些用例对应的是"看起来没问题、实际会让检索变差"的场景，
不是形式上的覆盖率测试。每一条都来自实际踩过的坑。
"""

from app.services.chunker import ChunkConfig, split_text

FENCE = "```"


def _cfg(**kw) -> ChunkConfig:
    base = {"chunk_size": 300, "chunk_overlap": 40}
    base.update(kw)
    return ChunkConfig(**base)


def _assert_code_blocks_closed(chunks: list[str]) -> None:
    for c in chunks:
        assert c.count(FENCE) % 2 == 0, f"代码块未闭合: ...{c[-60:]!r}"


class TestCodeBlockProtection:
    def test_code_block_not_split(self):
        """短代码块整体保留，即使它跨过了 chunk_size 边界。"""
        text = (
            "## 示例\n\n"
            "下面是一段说明文字，用来把前面的内容撑到接近上限。\n\n"
            f"{FENCE}js\nconst a = 1\nconst b = 2\n{FENCE}\n\n"
            "代码之后还有一点说明。\n"
        )
        chunks = [c.content for c in split_text(text, _cfg())]
        _assert_code_blocks_closed(chunks)
        # 代码内容必须完整出现在某一个块里
        assert any("const a = 1" in c and "const b = 2" in c for c in chunks)

    def test_long_code_block_sliced_with_fence(self):
        """超长代码按行切，但每片都要补回围栏和语言标记。"""
        body = "\n".join(f"const value{i} = {i}" for i in range(60))
        text = f"## 大段代码\n\n{FENCE}js\n{body}\n{FENCE}\n"
        chunks = [c.content for c in split_text(text, _cfg(chunk_size=200))]

        assert len(chunks) > 1, "超长代码应当被切片"
        _assert_code_blocks_closed(chunks)
        for c in chunks:
            if "const value" in c:
                assert c.count(FENCE) == 2, "每一片都应自带开闭围栏"
                assert "js" in c.split("\n")[0] or "```js" in c, "每一片都应保留语言标记"

    def test_unclosed_fence_in_source(self):
        """源文档围栏没闭合时，切片要自动补齐，不能产出破块。"""
        text = f"## 坏文档\n\n{FENCE}js\nconst a = 1\n"  # 故意不闭合
        chunks = [c.content for c in split_text(text, _cfg())]
        _assert_code_blocks_closed(chunks)


class TestTableProtection:
    def test_table_kept_whole(self):
        table = "| 城市 | 上限 |\n| --- | --- |\n| 一线 | 600 |\n| 二线 | 400 |"
        text = f"## 住宿标准\n\n说明文字。\n\n{table}\n\n后续文字。\n"
        chunks = [c.content for c in split_text(text, _cfg())]
        assert any("| 一线 | 600 |" in c and "| 二线 | 400 |" in c for c in chunks)

    def test_long_table_repeats_header(self):
        """超长表格切片后，每片都必须重复表头，否则数据行没有列名。"""
        rows = "\n".join(f"| 城市{i} | {i * 100} |" for i in range(40))
        table = f"| 城市 | 上限 |\n| --- | --- |\n{rows}"
        chunks = [c.content for c in split_text(table, _cfg(chunk_size=250))]

        assert len(chunks) > 1
        for c in chunks:
            assert "| 城市 | 上限 |" in c, f"缺少表头: {c[:60]!r}"
            assert "| --- | --- |" in c, "缺少分隔行"


class TestSentenceBoundary:
    def test_no_cut_inside_sentence(self):
        """长段落必须在句末标点处断开，不能切在句子中间。"""
        sents = [f"这是第{i}句话，用来测试句子边界是否被正确对齐。" for i in range(30)]
        text = "".join(sents)
        chunks = [c.content for c in split_text(text, _cfg(chunk_size=200, chunk_overlap=0))]

        for c in chunks[:-1]:
            assert c.rstrip()[-1] in "。！？；", f"块尾不是句末标点: {c[-30:]!r}"

    def test_no_half_word(self):
        """没有标点的长串（如英文标识符）也不能切出半个词。"""
        words = " ".join(f"identifier{i}" for i in range(80))
        chunks = [c.content for c in split_text(words, _cfg(chunk_size=150, chunk_overlap=0))]
        for c in chunks:
            assert c.startswith("identifier") or c.split(" ")[0].startswith("identifier")


class TestListAndHeading:
    def test_list_items_stay_with_parent(self):
        """列表整块保留，不会出现"第 1 项在上一块、第 2 项在下一块"。"""
        items = "\n".join(f"- **要点{i}**：这是第 {i} 条的说明文字" for i in range(12))
        text = f"## 要点\n\n{items}\n"
        cfg = _cfg(strategy="markdown_header", chunk_size=200)
        chunks = [c.content for c in split_text(text, cfg)]

        assert len(chunks) == 1, f"300 字列表应整块保留，实际 {len(chunks)} 块"
        assert "- **要点0**" in chunks[0] and "- **要点11**" in chunks[0]

    def test_bold_pseudo_heading_not_at_tail(self):
        """加粗伪标题不能孤立留在块尾。"""
        parts = []
        for i in range(8):
            body = f"这是第{i}段的具体说明，内容稍长一些用来推高长度。"
            parts.append(f"**{i}. 小标题{i}**\n\n{body}\n")
        text = "## 总览\n\n" + "\n".join(parts)
        chunks = [c.content.rstrip() for c in split_text(text, _cfg(chunk_size=200))]

        for c in chunks:
            last_line = c.split("\n")[-1].strip()
            assert not (last_line.startswith("**") and last_line.endswith("**")), (
                f"伪标题落在块尾: {last_line!r}"
            )

    def test_heading_injected(self):
        """切片应带标题前缀，脱离文档后仍能自解释。"""
        text = "## 住宿标准\n\n一线城市每晚不超过 600 元。\n"
        chunks = [c.content for c in split_text(text, _cfg())]
        assert chunks[0].startswith("## 住宿标准")

    def test_heading_can_be_disabled(self):
        text = "## 住宿标准\n\n一线城市每晚不超过 600 元。\n"
        chunks = [
            c.content
            for c in split_text(text, _cfg(strategy="markdown_header"), keep_heading=False)
        ]
        assert not chunks[0].startswith("## 住宿标准")

    def test_recursive_no_orphan_heading(self):
        """recursive 不感知标题，但孤立标题行必须附着到内容上，不能单独成块。"""
        items = "\n".join(f"- 要点{i}：说明文字" for i in range(10))
        text = f"## 要点\n\n{items}\n"
        cfg = _cfg(strategy="recursive", chunk_size=200)
        chunks = [c.content for c in split_text(text, cfg)]

        assert len(chunks) >= 1
        assert chunks[0].startswith("## 要点"), "标题应附着在内容块开头"
        assert all(c.strip() != "## 要点" for c in chunks), "标题不能孤立成块"


class TestDelimiterStrategy:
    def test_split_by_custom_marker(self):
        text = (
            "<!-- chunk -->第一部分内容，讲响应式。\n\n"
            "<!-- chunk -->第二部分内容，讲组件。\n\n"
            "<!-- chunk -->第三部分内容，讲路由。\n"
        )
        cfg = _cfg(strategy="delimiter", delimiter="<!-- chunk -->")
        chunks = [c.content for c in split_text(text, cfg)]

        assert len(chunks) == 3, f"应按标记切成 3 块，实际 {len(chunks)}"
        assert all("<!-- chunk -->" in c for c in chunks)

    def test_delimiter_not_merged(self):
        """指定标记时不合并——用户既然给了边界，就不能被"优化"掉。"""
        text = "\n\n".join(f"<!-- chunk -->很短的一段{i}。" for i in range(5))
        cfg = _cfg(strategy="delimiter", delimiter="<!-- chunk -->", merge_adjacent=True)
        chunks = [c.content for c in split_text(text, cfg)]
        assert len(chunks) == 5

    def test_delimiter_line_anchored(self):
        """标记按行首锚定：`## ` 不能误切 `### `。"""
        text = (
            "# 文档标题\n\n"
            "## 二级标题A\n\nA 的内容。\n\n"
            "### 三级标题A1\n\nA1 的内容。\n\n"
            "## 二级标题B\n\nB 的内容。\n"
        )
        cfg = _cfg(strategy="delimiter", delimiter="## ", min_chunk_size=10)
        chunks = [c.content for c in split_text(text, cfg)]

        # 纯切分视角：## A（含 ### A1）一块、## B 一块，共 2 块
        assert len(chunks) == 2, f"应只按二级标题切，实际 {len(chunks)}"
        joined = "\n".join(chunks)
        assert "### 三级标题A1" in joined, "三级标题必须保持完整"
        assert "## 二级标题B\n\nB 的内容。" in chunks[-1]
        # 开头的一级标题附着到第一块，不能孤立成块
        assert chunks[0].startswith("# 文档标题")

    def test_delimiter_missing_falls_back(self):
        """没配标记时不能崩，退回标题策略。"""
        text = "## 标题\n\n正文内容。\n"
        cfg = _cfg(strategy="delimiter", delimiter="")
        chunks = [c.content for c in split_text(text, cfg)]
        assert len(chunks) >= 1 and "正文内容" in chunks[0]


class TestConfigGuard:
    def test_overlap_larger_than_size(self):
        """overlap >= chunk_size 会导致死循环或爆炸，必须被纠正。"""
        cfg = ChunkConfig.from_dict({"chunk_size": 200, "chunk_overlap": 500})
        assert cfg.chunk_overlap < cfg.chunk_size

    def test_unknown_strategy_falls_back(self):
        cfg = ChunkConfig.from_dict({"strategy": "不存在的策略"})
        assert cfg.strategy == "recursive"

    def test_schema_defaults_match_chunker(self):
        """API schema 与 chunker 的默认值必须一致，否则改了参数不生效。"""
        from app.schemas.kb import ChunkConfigIn

        d = ChunkConfigIn()
        c = ChunkConfig()
        assert d.chunk_size == c.chunk_size
        assert d.chunk_overlap == c.chunk_overlap
        assert d.min_chunk_size == c.min_chunk_size
        assert d.keep_table_intact == c.keep_table_intact
        assert d.keep_code_intact == c.keep_code_intact


class TestRealDocument:
    def test_no_broken_code_in_vue_docs(self):
        """用真实语料回归：9 篇文档切完不能有破代码块。"""
        from pathlib import Path

        root = Path(__file__).resolve().parents[2] / "knowledge" / "vue3"
        if not root.exists():
            return

        cfg = ChunkConfig(strategy="markdown_header", chunk_size=400, chunk_overlap=60)
        for path in sorted(root.glob("*.md")):
            chunks = [c.content for c in split_text(path.read_text(encoding="utf-8"), cfg)]
            for c in chunks:
                assert c.count(FENCE) % 2 == 0, f"{path.name} 出现破代码块: ...{c[-60:]!r}"
