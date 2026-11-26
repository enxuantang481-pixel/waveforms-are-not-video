"""汇总 results/<设计>.csv：出“体积对读取耗时”的图和 Markdown 结果表。

用法：python -m wavebench.plot [设计 ...]
同名格式有多行时取最后一行。排序实验的行（order != hier）不进主图，单独出表。
"""
import csv
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager

from .common import RESULTS

BASE = "fst-lz4"       # 体积的相对基准：vcd2fst 默认档
BASE_READ = "fst-lz4+libfst"   # 读取耗时的相对基准：同一个文件用 GTKWave 的 libfst 读（见 ISSUES.md 第 10 条）
# 四个家族按固定顺序取参考配色的前四个色位，并各配一种标记形状（不只靠颜色区分）
FAM = {"control": ("#2a78d6", "o", "VCD / FST"), "bitpack": ("#eb6834", "D", "bit-packed + zstd"),
       "video": ("#1baf7a", "s", "video (FFV1 / x264)"), "table": ("#eda100", "^", "table (Parquet / DuckDB)")}
INK, MUTED, GRID = "#1a1a19", "#6b6a63", "#e6e4dc"


def load(design):
    rows = {}
    with open(RESULTS / f"{design}.csv", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            rows[r["format"]] = r
    return rows


def fnum(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def figure(design, rows):
    main = [r for r in rows.values() if r["order"] == "hier" and r["verified"] == "True" and fnum(r["rsig_s_med"])]
    fig, axes = plt.subplots(1, 2, figsize=(15, 7.5), sharex=True)
    for ax, key, title in ((axes[0], "rsig_s_med", "Read one signal, all cycles"),
                           (axes[1], "rtime_s_med", "Read all signals at one cycle")):
        for fam, (col, mk, lab) in FAM.items():
            pts = [r for r in main if r["family"] == fam]
            ax.scatter([float(r["size_bytes"]) / 1e6 for r in pts], [float(r[key]) * 1e3 for r in pts],
                       s=64, c=col, marker=mk, label=lab, edgecolors="white", linewidths=1.2, zorder=3)
            for r in pts:
                ax.annotate(r["format"], (float(r["size_bytes"]) / 1e6, float(r[key]) * 1e3), xytext=(5, 4),
                            textcoords="offset points", fontsize=6.5, color=MUTED, zorder=4)
        b = rows.get(BASE_READ) or rows.get(BASE)
        if b:
            ax.axvline(float(b["size_bytes"]) / 1e6, color="#b9b7ae", lw=1.2, ls="--", zorder=1)
            ax.axhline(float(b[key]) * 1e3, color="#b9b7ae", lw=1.2, ls="--", zorder=1)
        ax.set_xscale("log"); ax.set_yscale("log")
        ax.set_title(title, loc="left", fontsize=12, color=INK)
        ax.set_xlabel("file size (MB, log)", color=MUTED)
        ax.set_ylabel("median read time (ms, log)", color=MUTED)
        ax.grid(True, which="major", color=GRID, lw=0.6, zorder=0)
        for s in ("top", "right"):
            ax.spines[s].set_visible(False)
        for s in ("left", "bottom"):
            ax.spines[s].set_color(GRID)
        ax.tick_params(colors=MUTED)
    r0 = main[0]
    fig.suptitle(f"{design}: T={r0['T']} cycles x B={r0['B']} bits. Lower-left is better; dashed lines mark {BASE_READ}. "
                 "Timed on a busy machine (to be re-measured when idle).", x=0.01, ha="left", fontsize=11, color=INK)
    axes[0].legend(frameon=False, fontsize=9, loc="best")
    fig.tight_layout(rect=(0, 0, 1, 0.96))
    out = RESULTS / f"{design}_size_vs_read.png"
    fig.savefig(out, dpi=130)
    plt.close(fig)
    return out


def table(design, rows):
    b = rows[BASE]
    rb = rows.get(BASE_READ, b)
    bs, br, bt = float(b["size_bytes"]), float(rb["rsig_s_med"]), float(rb["rtime_s_med"])

    def line(r):
        if r["verified"] != "True" or not fnum(r["rsig_s_med"]):
            return f"| {r['format']} | {r.get('size_bytes') or '-'} | - | - | - | - | - | - | 未通过：{r['note'][:60]} |"
        s, a, t = float(r["size_bytes"]), float(r["rsig_s_med"]), float(r["rtime_s_med"])
        e = fnum(r["enc_s_med"])
        return (f"| {r['format']} | {s / 1e6:.3f} | {s / bs:.2f} | {'-' if e is None else f'{e:.2f}'} ({r['enc_n']}) | "
                f"{a * 1e3:.1f} ({r['rsig_n']}) | {a / br:.2f} | {t * 1e3:.1f} ({r['rtime_n']}) | {t / bt:.3f} | 通过 |")
    hdr = ("| 格式 | 体积 MB | 体积/FST | 编码秒（次数） | 读一个信号 ms（次数） | 相对 FST | 读一个时刻 ms（次数） | 相对 FST | 逐位校验 |\n"
           "|---|---|---|---|---|---|---|---|---|\n")
    main = [r for r in rows.values() if r["order"] == "hier"]
    out = [f"### {design}（T={b['T']}，B={b['B']}；体积基准 = {BASE}，{bs / 1e6:.3f} MB；读取耗时基准 = {BASE_READ}）\n", hdr + "\n".join(line(r) for r in main), ""]
    orows = [r for r in rows.values() if r["order"] != "hier"]
    if orows:
        out.append(f"#### {design}：信号顺序对体积的影响（MB；括号里是相对层次顺序的比值）\n")
        kinds = ["hier", "random", "toggle", "cluster_toggle", "cluster_value"]
        out.append("| 编码 | " + " | ".join(kinds) + " |\n|---|" + "---|" * len(kinds))
        bases = sorted({r["format"].split("@")[0] for r in orows})
        for bn in bases:
            h = rows.get(bn)
            cells = []
            for k in kinds:
                r = h if k == "hier" else rows.get(f"{bn}@{k}")
                if not r or r["verified"] != "True":
                    cells.append("-")
                else:
                    s = float(r["size_bytes"])
                    cells.append(f"{s / 1e6:.3f}" + (f" ({s / float(h['size_bytes']):.2f})" if h and k != "hier" else ""))
            out.append(f"| {bn} | " + " | ".join(cells) + " |")
        out.append("")
    return "\n".join(out)


def main(designs):
    md = []
    for d in designs:
        rows = load(d)
        print(figure(d, rows))
        md.append(table(d, rows))
    (RESULTS / "summary.md").write_text("\n".join(md), encoding="utf-8")
    print(RESULTS / "summary.md")


if __name__ == "__main__":
    main(sys.argv[1:] or ["picorv32", "serv", "biriscv"])
