"""命令行小工具：在你自己的波形上比较几种存法的体积和两种读法的耗时。

用法（WSL / Linux，先 source scripts/common.sh）：
    python -m wavebench.cli <波形.vcd 或 .fst> [--all] [--json 输出.json] [--keep] [--reps-note]

做的事：
  1. 读入波形（FST 先用 fst2vcd 转成 VCD，因为几种 FST 档位要由 vcd2fst 从 VCD 重新转）。
  2. 检查是两态、采样时刻等间隔，读成比特矩阵（规则和 RESULTS.md 里的测量完全相同）。
  3. 写出每种存法，完整解码后逐位核对，再测“取一个信号”和“取一个时刻”的耗时（固定种子抽样，取中位数）。
  4. 打印一张表：体积和耗时都给绝对值，也给相对“FST 默认档 + 进程内 libfst”的倍数。
中间文件放在 $WAVEBENCH_WORK/data|out/cli-<名字>-<进程号>/，跑完删除（--keep 保留）。

限制（遇到就停下并说明，不会悄悄改数据）：
  - 只支持两态（0/1）。有 x、z 或实数信号时：x/z 直接报错；实数信号跳过并列出。
  - 采样时刻必须落在一个等间隔网格上（t0 + k×step）。不等间隔会让矩阵大到不现实，这时报错。
"""
import argparse
import json
import math
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

from . import common as C
from . import formats as F
from .bench import run_one
from .common import Matrix, data_dir, med, out_dir, pick


class Refuse(SystemExit):
    pass


def scan_times(path, max_bytes):
    """第一遍：收集所有变化时刻，确定网格 (t0, step, T)，顺便检查两态。返回 (t0, step, T, 跳过的实数信号)。"""
    import pywellen
    w = pywellen.Waveform(str(path))
    c = lambda x: x() if callable(x) else x     # noqa: E731
    uni, skipped, nbits = None, [], 0
    for v in c(w.all_vars):
        name = c(v.full_name)
        if c(v.is_real) or c(v.bitwidth) is None:
            skipped.append(name)
            continue
        nbits += int(c(v.bitwidth))
        ch = list(c(v.signal))
        bad = next((x for x in ch if not isinstance(x[1], int)), None)
        if bad is not None:
            raise Refuse(f"Not supported: signal {name} has value {bad[1]!r} at time {bad[0]} (x or z). This tool handles two-state waveforms only.")
        t = np.unique(np.fromiter((x[0] for x in ch), dtype=np.int64, count=len(ch)))
        uni = t if uni is None else np.union1d(uni, t)
    if uni is None or len(uni) == 0:
        raise Refuse("No usable signals in the waveform.")
    t0 = int(uni[0])
    step = int(np.gcd.reduce(np.diff(uni))) if len(uni) > 1 else 1
    T = (int(uni[-1]) - t0) // step + 1
    need = nbits * math.ceil(T / 8)
    if need > max_bytes:
        raise Refuse(f"Not supported: the change times do not sit on a coarse, evenly spaced grid (grid step {step}; "
                     f"that would expand to {T:,} time points x {nbits:,} bits = {need / 1e9:.1f} GB, limit {max_bytes / 1e9:.1f} GB). "
                     "--max-gb raises the limit, but this usually means real timestamps or glitches, which a per-cycle comparison does not fit.")
    return t0, step, T, skipped


FORMATS_DEFAULT = lambda: [  # noqa: E731
    F.FstInproc("fst-lz4+inproc", ["-4"]),
    F.FstInproc("fst-zlib-c+inproc", ["-Z", "-c"]),
    F.BitpackZstd("sm", 19),
    F.Table("parquet", "wide", 19, 65536),
    F.Video("ffv1", "strip", 8),
]
FORMATS_EXTRA = lambda: [  # noqa: E731
    F.Wellen("vcd", "wave.vcd"),
    F.Wellen("vcd.zst19", None, zst_level=19),
    F.Table("parquet", "long", 3, 65536),
    F.Table("duckdb", "wide"),
    F.Video("x264", "strip", 8, preset="medium"),
]


class Collect:
    """代替 csv.DictWriter，把 run_one 写的行收集起来。"""
    def __init__(self):
        self.rows = []

    def writerow(self, r):
        self.rows.append(r)

    def flush(self):
        pass


def fmt_bytes(b):
    for u, k in (("GB", 1e9), ("MB", 1e6), ("KB", 1e3)):
        if b >= k:
            return f"{b / k:.2f} {u}"
    return f"{b} B"


def fmt_s(s):
    if s in ("", None):
        return "-"
    s = float(s)
    return f"{s:.2f} s" if s >= 1 else f"{s * 1000:.1f} ms"


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m wavebench.cli", description="Compare size and read time of several storage formats on your own waveform (two-state VCD/FST, evenly spaced samples).")
    ap.add_argument("wave", help="input .vcd or .fst file")
    ap.add_argument("--all", action="store_true", help="besides the 5 default formats, also VCD, VCD+zstd, Parquet long, DuckDB wide, x264")
    ap.add_argument("--json", help="also write the results as JSON")
    ap.add_argument("--keep", action="store_true", help="keep the intermediate files")
    ap.add_argument("--max-gb", type=float, default=2.0, help="memory limit for the bit matrix in GB (default 2)")
    a = ap.parse_args(argv)

    src = Path(a.wave).resolve()
    if not src.exists():
        raise Refuse(f"File not found: {src}")
    kind = src.suffix.lower()
    if kind not in (".vcd", ".fst"):
        raise Refuse("Only .vcd or .fst files are accepted.")
    for tool in ("vcd2fst", "fst2vcd"):
        if shutil.which(tool) is None:
            raise Refuse(f"{tool} not found (it ships with GTKWave).")
    if not (C.WORK / "bin" / "libfstq.so").exists():
        raise Refuse("libfstq.so not found; run bash scripts/build_tools.sh first.")

    design = f"cli-{src.stem}-{os.getpid()}"
    d = data_dir(design)
    d.mkdir(parents=True, exist_ok=True)
    try:
        t_start = time.perf_counter()
        vcd = d / "wave.vcd"
        if kind == ".vcd":
            print("[1/4] Using the VCD as is", flush=True)
            os.symlink(src, vcd)
        else:
            print("[1/4] FST -> VCD (fst2vcd)...", flush=True)
            subprocess.run(["fst2vcd", "-f", str(src), "-o", str(vcd)], check=True, stdout=subprocess.DEVNULL)
        print("[2/4] Checking two-state values and the sample grid...", flush=True)
        t0, step, T, skipped = scan_times(vcd, int(a.max_gb * 1e9))
        C.TIME.update(t0=t0, step=step)
        from .to_matrix import read_wave
        bits, T, signals, st = read_wave(vcd, T)
        m = Matrix(bits, T, signals)
        print(f"      {m.T:,} time points (t0={t0}, step {step}), {len(m.signals):,} signals, {m.B:,} bits"
              + (f"; skipped {len(skipped)} real-valued signals" if skipped else ""), flush=True)
        sigs, times = pick(m)
        fmts = FORMATS_DEFAULT() + (FORMATS_EXTRA() if a.all else [])
        print(f"[3/4] Writing, verifying bit for bit and timing {len(fmts)} formats (seconds to minutes each)...", flush=True)
        col = Collect()
        for f in fmts:
            run_one(design, m, f, sigs, times, col, col)
        rows = col.rows
        ref = next((r for r in rows if r["format"] == "fst-lz4+inproc" and r.get("verified")), None)
        print("[4/4] Results (x = relative to default FST read with in-process libfst; below 1 means smaller or faster)\n")
        head = f"{'format':<30} {'size':>11} {'x':>7} {'one cycle':>11} {'x':>7} {'one signal':>11} {'x':>7}  verified"
        print(head)
        print("-" * 104)
        for r in rows:
            sz = r.get("size_bytes") or 0
            rel = lambda k: (f"{float(r[k]) / float(ref[k]):.3g}" if ref and r.get(k) not in ("", None) and ref.get(k) else "-")  # noqa: E731
            szr = f"{sz / ref['size_bytes']:.3g}" if ref and sz else "-"
            ok = "yes" if r.get("verified") else "FAILED " + r.get("note", "")[:40]
            print(f"{r['format']:<30} {fmt_bytes(sz) if sz else '-':>11} {szr:>7} {fmt_s(r.get('rtime_s_med')):>11} {rel('rtime_s_med'):>7} "
                  f"{fmt_s(r.get('rsig_s_med')):>11} {rel('rsig_s_med'):>7}  {ok}")
        print(f"\nInput: {src.name}, {fmt_bytes(src.stat().st_size)}. Total time {time.perf_counter() - t_start:.0f} s."
              f" Load average {os.getloadavg()[0]:.2f} (on a busy machine, read the timings as orders of magnitude only).")
        if a.json:
            out = dict(input=str(src), T=m.T, B=m.B, n_signals=len(m.signals), t0=t0, step=step,
                       skipped_real=skipped, loadavg=os.getloadavg(), rows=rows)
            Path(a.json).write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
            print(f"Wrote {a.json}")
        return 0 if all(r.get("verified") for r in rows) else 1
    finally:
        if a.keep:
            print(f"Intermediate files kept in {d} and {out_dir(design)}")
        else:
            shutil.rmtree(d, ignore_errors=True)
            shutil.rmtree(C.WORK / "out" / design, ignore_errors=True)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Refuse as e:
        print(e, file=sys.stderr)
        sys.exit(2)
