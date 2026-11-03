"""切片质量诊断：不看代码，看切完的块到底变成什么样。

三类问题各对应一个指标：
1. 结构破坏 —— 代码块被切成两半，两边都是 ``` 奇数个，渲染出来是破的
2. 语义截断 —— 块尾停在半句话（末字符不是句末标点/闭合符），模型拿到的是残句
3. 超长溢出 —— 合并 short chunk 时没检查上限，块超过 chunk_size 很多

用法：
    python -m scripts.diagnose_chunks ../knowledge/vue3 400 60
    python -m scripts.diagnose_chunks ../knowledge/vue3 400 60 --strategy delimiter
"""

import re
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.chunker import ChunkConfig, split_text  # noqa: E402

SENT_END = "。！？；.!?;：:）)】」』\"'`|"
CLOSERS = ("```", "~~~", "|", "</", "】", "）", ")")
# 列表项本来就不一定带句号，不能算截断
LIST_TAIL_RE = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+")
BOLD_TAIL_RE = re.compile(r"^\*\*[^*\n]{1,60}\*\*[：:]?$")


def classify_tail(body: str) -> str:
    """块尾分类：句子截断 / 列表项 / 伪标题 / 正常。"""
    tail = body.rstrip()
    if not tail:
        return "empty"
    last_line = tail.split("\n")[-1].strip()
    if BOLD_TAIL_RE.match(last_line):
        return "bold_title"
    if LIST_TAIL_RE.match(last_line):
        return "list_item"
    if tail[-1] in SENT_END or tail.endswith(CLOSERS):
        return "ok"
    return "cut"


def diagnose_dir(root: Path, cfg: ChunkConfig) -> dict:
    files = sorted(p for p in root.iterdir() if p.suffix.lower() == ".md")
    total_chunks = 0
    unclosed_code = 0
    cut_sentence = 0
    bold_tail = 0
    list_tail = 0
    over_size = 0
    tiny = 0
    sizes: list[int] = []
    samples: list[tuple[str, str, str]] = []

    for path in files:
        text = path.read_text(encoding="utf-8")
        chunks = split_text(text, cfg)
        total_chunks += len(chunks)
        for ch in chunks:
            body = ch.content
            sizes.append(ch.char_count)

            # 1) 代码块未闭合：``` 出现奇数次
            if body.count("```") % 2 == 1 or body.count("~~~") % 2 == 1:
                unclosed_code += 1
                if len(samples) < 6:
                    samples.append((path.name, "代码块未闭合", body[-70:]))

            # 2) 尾部语义完整性
            kind = classify_tail(body)
            if kind == "bold_title":
                bold_tail += 1
                if len(samples) < 6:
                    samples.append((path.name, "伪标题落在块尾", body[-70:]))
            elif kind == "list_item":
                list_tail += 1
            elif kind == "cut":
                cut_sentence += 1
                if len(samples) < 6:
                    samples.append((path.name, "句子被截断", body[-70:]))

            # 3) 超长 / 过短
            if ch.char_count > cfg.chunk_size * 1.2:
                over_size += 1
            if ch.char_count < cfg.min_chunk_size:
                tiny += 1

    return {
        "files": len(files),
        "chunks": total_chunks,
        "avg": round(statistics.mean(sizes), 1) if sizes else 0,
        "p95": round(statistics.quantiles(sizes, n=20)[-1], 1) if len(sizes) > 20 else 0,
        "max": max(sizes) if sizes else 0,
        "min": min(sizes) if sizes else 0,
        "unclosed_code": unclosed_code,
        "cut_sentence": cut_sentence,
        "bold_tail": bold_tail,
        "list_tail": list_tail,
        "over_size": over_size,
        "tiny": tiny,
        "samples": samples,
    }


def main() -> int:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else "../knowledge/vue3")
    size = int(sys.argv[2]) if len(sys.argv) > 2 else 400
    overlap = int(sys.argv[3]) if len(sys.argv) > 3 else 60
    strategy = "markdown_header"
    delimiter = ""
    for i, a in enumerate(sys.argv):
        if a == "--strategy" and i + 1 < len(sys.argv):
            strategy = sys.argv[i + 1]
        if a == "--delimiter" and i + 1 < len(sys.argv):
            delimiter = sys.argv[i + 1]

    cfg = ChunkConfig(
        strategy=strategy, chunk_size=size, chunk_overlap=overlap, delimiter=delimiter
    )
    r = diagnose_dir(root, cfg)

    label = f"{strategy}" + (f" / delimiter={delimiter!r}" if delimiter else "")
    print(f"策略 {label} / chunk_size={size} / overlap={overlap}")
    print(f"文件 {r['files']} 个  切片 {r['chunks']} 个")
    print(f"长度  平均 {r['avg']}  p95 {r['p95']}  最大 {r['max']}  最小 {r['min']}")
    print()
    total = max(r["chunks"], 1)

    def pct(n: int) -> str:
        return f"{n / total * 100:.1f}%"

    print("—— 质量指标 ——")
    print(f"代码块未闭合      : {r['unclosed_code']:>3} 个  ({pct(r['unclosed_code'])})")
    print(f"句子被截断        : {r['cut_sentence']:>3} 个  ({pct(r['cut_sentence'])})")
    print(f"伪标题落在块尾    : {r['bold_tail']:>3} 个  ({pct(r['bold_tail'])})")
    print(f"以列表项结尾(正常): {r['list_tail']:>3} 个")
    print(f"超出 chunk_size   : {r['over_size']:>3} 个")
    print(f"短于 min_chunk    : {r['tiny']:>3} 个")
    if r["samples"]:
        print("\n—— 未闭合样例（尾部 70 字）——")
        for name, kind, tail in r["samples"]:
            print(f"  [{name}] {kind}: …{tail!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
