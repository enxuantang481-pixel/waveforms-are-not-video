"""对一个设计跑一组格式：编码计时、体积、逐位校验、两种读法计时。结果追加到 results/<设计>.csv。

用法：python -m wavebench.bench <设计> <组名> [只跑名字里含这个子串的格式]
组名：min（最低交付）、controls、fstnative、video、table、order、key（关键格式顺序复测）、all
第三个参数可以写成 a+b，表示名字里同时含 a 和 b
"""
import csv
import datetime
import os
import sys
import time
import traceback

import numpy as np

from . import formats as F
from .common import RESULTS, Matrix, med, out_dir, pick, sha_bits
from .ordering import make_order

FIELDS = ["design", "T", "B", "format", "family", "order", "size_bytes", "meta_bytes", "verified",
          "enc_s_med", "enc_s_min", "enc_n", "rsig_s_med", "rsig_s_min", "rsig_n",
          "rtime_s_med", "rtime_s_min", "rtime_n", "loadavg", "when", "command", "note"]


def groups(m, which):
    g = {}
    g["controls"] = [
        F.Wellen("vcd", "wave.vcd"),
        F.Wellen("vcd.zst3", None, zst_level=3),
        F.Wellen("vcd.zst19", None, zst_level=19),
        F.Wellen("fst-verilator", "wave.verilator.fst"),
        F.Wellen("fst-lz4", None, tool=["-4"]),
        F.Wellen("fst-fastlz", None, tool=["-F"]),
        F.Wellen("fst-zlib", None, tool=["-Z"]),
        F.Wellen("fst-lz4-c", None, tool=["-4", "-c"]),
        F.Wellen("fst-zlib-c", None, tool=["-Z", "-c"]),
        F.BitpackZstd("sm", 19), F.BitpackZstd("tm", 19), F.BitpackZstd("sm", 3),
    ]
    g["video"] = [
        F.Video("ffv1", "frame", 1), F.Video("ffv1", "frame", 8),
        F.Video("ffv1", "strip", 1), F.Video("ffv1", "strip", 8),
        F.Video("ffv1", "strip", 1, extra=["-coder", "1", "-context", "1"]),
        F.Video("x264", "frame", 1, preset="ultrafast"), F.Video("x264", "frame", 1, preset="medium"),
        F.Video("x264", "frame", 8, preset="medium"),
        F.Video("x264", "strip", 1, preset="ultrafast"), F.Video("x264", "strip", 1, preset="medium"),
        F.Video("x264", "strip", 8, preset="medium"),
        F.Video("x264", "frame", 1, preset="medium", extra=["-g", "32"]),
    ]
    g["table"] = [
        F.Table("parquet", "wide", 3, 65536), F.Table("parquet", "wide", 19, 65536),
        F.Table("parquet", "wide", 3, 4096),
        F.Table("parquet", "long", 3, 65536), F.Table("parquet", "long", 19, 65536),
        F.Table("duckdb", "wide"), F.Table("duckdb", "long"),
    ]
    g["fstnative"] = [F.FstNative("fst-lz4+libfst", ["-4"]), F.FstNative("fst-zlib-c+libfst", ["-Z", "-c"])]
    g["inproc"] = [F.FstInproc("fst-lz4+inproc", ["-4"]), F.FstInproc("fst-zlib-c+inproc", ["-Z", "-c"])]
    # 进程内 libfst 和宽表在同一轮里顺序比（修订方案二第 3 项）
    g["inproc_vs_table"] = g["inproc"] + g["fstnative"] + [g["table"][1], g["table"][0]]
    # 顺序复测用的关键格式：两个 FST 原生读取、最小的打包矩阵、最好的宽表、读时刻最快的视频
    g["key"] = g["fstnative"] + [g["controls"][9], g["table"][1], g["table"][0], g["video"][3], g["video"][10]]
    g["min"] = [g["controls"][0], g["controls"][1], g["controls"][4], g["video"][2], g["table"][0]]
    if which == "order":
        g["order"] = []
        for kind in ("random", "toggle", "cluster_toggle", "cluster_value"):
            t0 = time.perf_counter()
            o = make_order(m, kind)
            print(f"[order] {kind}: {time.perf_counter() - t0:.1f}s", flush=True)
            tag = "@" + kind
            for f in (F.Video("ffv1", "strip", 1, order=o, tag=tag), F.Video("x264", "strip", 1, order=o, tag=tag),
                      F.Video("ffv1", "frame", 1, order=o, tag=tag), F.Video("x264", "frame", 1, order=o, tag=tag),
                      F.BitpackZstd("sm", 19, order=o, tag=tag), F.BitpackZstd("tm", 19, order=o, tag=tag)):
                f.order_kind = kind
                g["order"].append(f)
    g["all"] = g["controls"] + g["fstnative"] + g["video"] + g["table"]
    return g[which]


def _adaptive(fn, args_list, checker):
    """先跑一次看快慢。快的：每个参数 3 次；慢的（>1 秒）：只用第一个参数跑 3 次。每次都核对返回值。"""
    t0 = time.perf_counter()
    r = fn(args_list[0])
    first = time.perf_counter() - t0
    checker(args_list[0], r)
    ts = [first]
    plan = [args_list[0]] * 2 if first > 1.0 else [args_list[0]] * 2 + [a for a in args_list[1:] for _ in range(3)]
    for a in plan:
        t0 = time.perf_counter()
        r = fn(a)
        ts.append(time.perf_counter() - t0)
        checker(a, r)
    return ts


def run_one(design, m, f, sigs, times, writer, fh):
    ext = {"control": "", "bitpack": "", "video": ".mkv", "table": ".parquet" if getattr(f, "engine", "") == "parquet" else ".duckdb"}[f.family]
    path = str(out_dir(design) / (f.name.replace("@", "_at_") + ext))
    row = dict(design=design, T=m.T, B=m.B, format=f.name, family=f.family,
               order=getattr(f, "order_kind", "hier"), when=datetime.datetime.now().isoformat(timespec="seconds"),
               loadavg=os.getloadavg()[0], note="")
    try:
        enc = []
        for k in range(3):
            t0 = time.perf_counter()
            files, cmd = f.encode(m, path, design)
            enc.append(time.perf_counter() - t0)
            if enc[0] > 20:      # 单次超过 20 秒的只编一次
                break
        if f.name in ("vcd", "fst-verilator"):
            enc, row["note"] = [], "由仿真器直接写出，不单独计编码时间；"
        meta = 0 if f.has_meta else len(m.meta_blob(f.order))
        row.update(command=cmd, size_bytes=sum(os.path.getsize(p) for p in files) + meta, meta_bytes=meta,
                   enc_s_med=med(enc) if enc else "", enc_s_min=min(enc) if enc else "", enc_n=len(enc))
        # 逐位校验
        dec = f.decode_all(m, path)
        ok = dec.shape == m.bits_sm.shape and np.array_equal(dec, m.bits_sm) and sha_bits(dec, m.T) == m.sha()
        row["verified"] = bool(ok)
        del dec
        if not ok:
            row["note"] += "解码后与原矩阵不一致；"
        else:
            def chk_s(i, r):
                s = m.signals[i]
                exp = np.unpackbits(m.bits_sm[s["col"]:s["col"] + s["width"]], axis=1)[:, :m.T]
                assert r.shape == exp.shape and np.array_equal(r, exp), f"读法一结果错 信号{i}"

            def chk_t(t, r):
                assert np.array_equal(np.asarray(r, dtype=np.uint8), m.column(t)), f"读法二结果错 周期{t}"
            ts = _adaptive(lambda i: f.read_signal(m, path, i), sigs, chk_s)
            row.update(rsig_s_med=med(ts), rsig_s_min=min(ts), rsig_n=len(ts))
            ts = _adaptive(lambda t: f.read_time(m, path, t), times, chk_t)
            row.update(rtime_s_med=med(ts), rtime_s_min=min(ts), rtime_n=len(ts))
    except Exception as e:
        row["verified"] = row.get("verified", False)
        row["note"] += "失败: " + repr(e)[:300]
        traceback.print_exc()
    writer.writerow(row)
    fh.flush()
    g = lambda k: f"{row[k]:.5g}" if isinstance(row.get(k), float) else str(row.get(k, ""))  # noqa: E731  不能截字符串：8.6e-05 会被截成 8.6
    print(f"{f.name:42s} size={row.get('size_bytes', '?'):>11} ok={row.get('verified')} "
          f"enc={g('enc_s_med')} rsig={g('rsig_s_med')} rtime={g('rtime_s_med')} {row['note'][:120]}", flush=True)


def main(design, which, only=None):
    m = Matrix.load(design)
    sigs, times = pick(m)
    RESULTS.mkdir(exist_ok=True)
    p = RESULTS / f"{design}.csv"
    new = not p.exists()
    with open(p, "a", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        if new:
            w.writeheader()
        for f in groups(m, which):
            if only and not all(x in f.name for x in only.split("+")):
                continue
            run_one(design, m, f, sigs, times, w, fh)


if __name__ == "__main__":
    main(*sys.argv[1:])
