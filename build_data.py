"""从 results/ 的原始 CSV 生成网站用的数据文件 web/data/bench.js（页面里的数字都从这里来，不手抄）。

用法（仓库根目录）：python web/build_data.py
- 某个波形如果在 results/idle/ 里有空闲复测的结果，就只用复测的；否则用 results/ 里第一、二轮的，并标成“机器不空闲”。
- 同一格式在同一份 CSV 里测过多次的，取最后一次（后面的轮次是顺序复测）。
- 只收逐位校验通过的行；排序实验（order 不是 hier 的行）不进主图。
- 体积基准：同一波形的 FST 默认档（vcd2fst -4）文件；读取耗时基准：进程内 libfst 读同一个文件（fst-lz4+inproc）。
另外从 sample/ 里截一小段 PicoRV32 波形给首页的示意图用。依赖：Python 3 标准库加 numpy。
"""
import base64
import csv
import json
import re
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
RES = ROOT / "results"
OUT = ROOT / "web" / "data" / "bench.js"

WAVES = [  # (id, 设计, 中文标签, 英文标签)
    ("picorv32", "PicoRV32", "PicoRV32，20 万周期", "PicoRV32, 200k cycles"),
    ("serv", "SERV", "SERV，26 万周期", "SERV, 262k cycles"),
    ("serv_x10", "SERV", "SERV，262 万周期", "SERV, 2.6M cycles"),
    ("biriscv", "biRISC-V", "biRISC-V，6.6 万周期", "biRISC-V, 66k cycles"),
    ("biriscv_x4", "biRISC-V", "biRISC-V，26 万周期", "biRISC-V, 262k cycles"),
]


def label(fmt):
    """格式代号 -> (中文名, 英文名, 族, 读取方式)。族：base（VCD/FST 对照）、bitpack、video、table。"""
    if fmt == "vcd":
        return "VCD", "VCD", "base", "pywellen"
    m = re.fullmatch(r"vcd\.zst(\d+)", fmt)
    if m:
        return f"VCD + zstd -{m[1]}", f"VCD + zstd -{m[1]}", "base", "pywellen"
    fst = {"fst-lz4": ("FST 默认档（LZ4）", "FST default (LZ4)"),
           "fst-zlib-c": ("FST 最小档（zlib，-c）", "FST smallest (zlib, -c)"),
           "fst-fastlz": ("FST FastLZ", "FST FastLZ"), "fst-zlib": ("FST zlib", "FST zlib"),
           "fst-lz4-c": ("FST LZ4，-c", "FST LZ4, -c"),
           "fst-verilator": ("FST（Verilator 直接写）", "FST (written by Verilator)")}
    base, _, reader = fmt.partition("+")
    if base in fst:
        zh, en = fst[base]
        rd = {"": "pywellen", "libfst": "libfst（子进程）", "inproc": "libfst（进程内）"}[reader]
        return zh, en, "base", rd
    m = re.fullmatch(r"bitpack-(sm|tm)\.zst(\d+)", fmt)
    if m:
        zh = {"sm": "按信号排", "tm": "按时间排"}[m[1]]
        en = {"sm": "signal-major", "tm": "time-major"}[m[1]]
        return f"打包矩阵 + zstd -{m[2]}（{zh}）", f"Bit-pack + zstd -{m[2]} ({en})", "bitpack", "numpy"
    m = re.fullmatch(r"(ffv1|x264)(?:[-_]([a-z0-9_]+))?-(frame|strip)-(\d)bpp", fmt)
    if m:
        codec = {"ffv1": "FFV1", "x264": "x264 无损"}[m[1]]
        codec_en = {"ffv1": "FFV1", "x264": "x264 lossless"}[m[1]]
        opt = m[2] or ""
        opt = {"coder1_context1": "coder 1 context 1", "medium": "", "ultrafast": "ultrafast",
               "medium_g32": "GOP 32"}.get(opt, opt)
        lay = {"frame": ("每周期一帧", "frame per cycle"), "strip": ("条带", "strip")}[m[3]]
        zh = " ".join(x for x in (codec, lay[0], f"{m[4]}bpp", opt) if x)
        en = " ".join(x for x in (codec_en, lay[1], f"{m[4]}bpp", opt) if x)
        return zh, en, "video", "PyAV"
    m = re.fullmatch(r"parquet-(wide|long)-zstd(\d+)-rg(\d+)", fmt)
    if m:
        sh = {"wide": ("宽表", "wide"), "long": ("长表", "long")}[m[1]]
        rg = "" if m[3] == "65536" else f"，行组 {m[3]}"
        rg_en = "" if m[3] == "65536" else f", row group {m[3]}"
        return f"Parquet {sh[0]} zstd -{m[2]}{rg}", f"Parquet {sh[1]} zstd -{m[2]}{rg_en}", "table", "pyarrow"
    m = re.fullmatch(r"duckdb-(wide|long)", fmt)
    if m:
        sh = {"wide": ("宽表", "wide"), "long": ("长表", "long")}[m[1]]
        return f"DuckDB {sh[0]}", f"DuckDB {sh[1]}", "table", "duckdb"
    raise ValueError(f"不认识的格式 {fmt}")


def fnum(x):
    return float(x) if x not in ("", None) else None


def load(wid):
    for src, p in (("idle", RES / "idle" / f"{wid}.csv"), ("busy", RES / f"{wid}.csv")):
        if p.exists():
            rows = [r for r in csv.DictReader(open(p, encoding="utf-8")) if r["design"] == wid]
            # 复测没跑完（还没有进程内 libfst 的基准行）就先不用它
            if any(r["format"] == "fst-lz4+inproc" and r["verified"] == "True" for r in rows):
                return src, p, rows
    raise FileNotFoundError(wid)


def build():
    waves, rows_out = [], []
    for wid, design, zh, en in WAVES:
        src, path, rows = load(wid)
        last = {}
        for r in rows:
            if r["order"] != "hier" or r["verified"] != "True":
                continue
            last[r["format"]] = r            # 后面的行覆盖前面的
        size_ref = next(int(last[k]["size_bytes"]) for k in ("fst-lz4", "fst-lz4+inproc", "fst-lz4+libfst") if k in last)
        ref = last.get("fst-lz4+inproc")
        if ref is None:
            raise SystemExit(f"{wid}: 没有进程内 libfst 的基准行")
        rs_ref, rt_ref = float(ref["rsig_s_med"]), float(ref["rtime_s_med"])
        loads = [float(r["loadavg"]) for r in last.values() if r["loadavg"]]
        any_r = next(iter(last.values()))
        waves.append(dict(id=wid, design=design, zh=zh, en=en, T=int(any_r["T"]), B=int(any_r["B"]),
                          source=src, csv=str(path.relative_to(ROOT)).replace("\\", "/"),
                          fst_default_bytes=size_ref, ref_rsig_s=rs_ref, ref_rtime_s=rt_ref,
                          loadavg_min=min(loads), loadavg_max=max(loads),
                          when_first=min(r["when"] for r in last.values()), when_last=max(r["when"] for r in last.values())))
        for fmt, r in last.items():
            lzh, len_, fam, reader = label(fmt)
            size = int(r["size_bytes"])
            rs, rt = fnum(r["rsig_s_med"]), fnum(r["rtime_s_med"])
            rows_out.append(dict(w=wid, fmt=fmt, zh=lzh, en=len_, family=fam, reader=reader,
                                 size=size, size_rel=size / size_ref,
                                 rsig_s=rs, rtime_s=rt,
                                 rsig_rel=rs / rs_ref if rs else None, rtime_rel=rt / rt_ref if rt else None,
                                 rsig_n=int(r["rsig_n"] or 0), rtime_n=int(r["rtime_n"] or 0),
                                 enc_s=fnum(r["enc_s_med"]), loadavg=fnum(r["loadavg"]), when=r["when"],
                                 command=r["command"]))
    return waves, rows_out


def hero():
    """首页示意图：PicoRV32 前 512 个周期、前 1024 个比特（打包后 base64），以及几根信号的位置。"""
    z = np.load(ROOT / "sample" / "picorv32_first4096.npz")
    sigs = json.load(open(ROOT / "sample" / "picorv32_signals.json", encoding="utf-8"))
    NB, NC = 1024, 512
    bits = z["bits_sm"][:NB, :NC // 8]                     # (1024, 64) 每行是一个比特在 512 个周期上的取值
    want = ["TOP.wb_top.mem_valid", "TOP.wb_top.mem_instr", "TOP.wb_top.mem_la_read", "TOP.wb_top.mem_la_write",
            "TOP.wb_top.mem_wstrb", "TOP.wb_top.mem_addr", "TOP.wb_top.mem_rdata", "TOP.wb_top.uut.reg_pc"]
    pick = [dict(name=s["name"].replace("TOP.wb_top.", "").replace("uut.", ""), width=s["width"], col=s["col"])
            for s in sigs if s["name"] in want]
    assert len(pick) == len(want) and all(p["col"] + p["width"] <= NB for p in pick)
    return dict(rows=NB, cycles=NC, total_bits=int(z["bits_sm"].shape[0]), bits_b64=base64.b64encode(bits.tobytes()).decode(),
                signals=pick)


def orientation():
    """和 vcd2df 的方向对照（results/vcd2df_*.csv，只有体积）。"""
    names = {"vcd": ("VCD", "VCD", "base"), "fst-lz4": ("FST 默认档", "FST default", "base"),
             "fst-zlib-c": ("FST 最小档", "FST smallest", "base"),
             "bitpack-sm.zst19": ("打包矩阵 + zstd -19", "Bit-pack + zstd -19", "bitpack"),
             "parquet 一列一个信号 (zstd)": ("Parquet，一列一个信号", "Parquet, one column per signal", "ours"),
             "parquet 一列一个时间点 (zstd)": ("Parquet，一列一个时间点（vcd2df 的方向）", "Parquet, one column per time point (vcd2df's orientation)", "theirs"),
             "vcd2df 1.0 原包 -> to_parquet (zstd)": ("vcd2df 原包输出（有损）", "vcd2df package output (lossy)", "pkg")}
    out = []
    for p in sorted(RES.glob("vcd2df_*.csv")):
        rows = list(csv.DictReader(open(p, encoding="utf-8")))
        items = [dict(zh=names[r["format"]][0], en=names[r["format"]][1], kind=names[r["format"]][2], size=int(r["size_bytes"]))
                 for r in rows if r["format"] in names and r["size_bytes"]]
        failed = [r["note"] for r in rows if r["format"].startswith("vcd2df") and not r["size_bytes"]]
        kept = [re.search(r"VCD 里有 (\d+) 个 \$var，它保留 (\d+) 个", r["note"]) for r in rows if r["format"].startswith("vcd2df") and r["size_bytes"]]
        kept = [int(kept[0][1]), int(kept[0][2])] if kept and kept[0] else None
        out.append(dict(design=rows[0]["design"].split("_")[0], T=int(rows[0]["T"]), B=int(rows[0]["B"]), pkg_kept=kept,
                        csv=str(p.relative_to(ROOT)).replace("\\", "/"), items=items, pkg_failed=bool(failed)))
    return out


def conditions():
    p = RES / "idle" / "conditions.log"
    # 不把本机账户名带进网页
    return re.sub(r"/home/[^/\s]+", "~", p.read_text(encoding="utf-8")) if p.exists() else ""


def main():
    waves, rows = build()
    data = dict(generated_from="results/*.csv, results/idle/*.csv", waves=waves, rows=rows, hero=hero(),
                orientation=orientation(), idle_conditions=conditions())
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("// 由 web/build_data.py 生成，不要手改\nwindow.BENCH = " + json.dumps(data, ensure_ascii=False, separators=(",", ":")) + ";\n",
                   encoding="utf-8", newline="\n")
    for w in waves:
        n = sum(r["w"] == w["id"] for r in rows)
        print(f"{w['id']:12s} {w['source']:5s} {n:3d} 行  FST 默认档 {w['fst_default_bytes']:>10}  load {w['loadavg_min']:.2f}-{w['loadavg_max']:.2f}")
    print("写出", OUT, OUT.stat().st_size, "字节")


if __name__ == "__main__":
    main()
