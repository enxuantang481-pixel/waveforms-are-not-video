"""和已有工作 vcd2df（arXiv 2505.06470）的对照：同一份短波形上，比较两种表的方向。

用法：python -m wavebench.vcd2df_compare <设计名>     （例如 picorv32_t2201，需要 wave.vcd 还在）

三样东西：
  A. 真的 vcd2df 1.0（pip 装的原包）读我们的 VCD，再按论文的做法 DataFrame.to_parquet。
     它一行一个寄存器、一列一个时间点；按“模块内的短名字”去重，所以不同模块里同名的信号会被丢掉；
     这一份不要求和我们的矩阵逐位相同，只报体积和它保留了多少变量。
  B. 我们的矩阵按它的方向存（一行一个信号段，一列一个时间点），无损，读回来逐位核对。
  C. 我们原来的方向（一行一个周期，一列一个信号段），无损，逐位核对。
再列出同一份波形的 VCD、FST 默认档、FST 最小档、打包矩阵加 zstd19 的体积。
"""
import csv
import os
import subprocess
import sys
import time

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import zstandard

from . import formats as F
from .common import RESULTS, Matrix, data_dir, out_dir, pack_sm_from_tm_chunks


def main(design):
    m = Matrix.load(design)
    d, o = data_dir(design), out_dir(design)
    vcd = d / "wave.vcd"
    rows = []

    def add(name, size, note="", verified=""):
        rows.append(dict(design=design, T=m.T, B=m.B, format=name, size_bytes=size, verified=verified, note=note))
        print(f"{name:44s} {size:>10}  {verified!s:5}  {note}", flush=True)

    add("vcd", os.path.getsize(vcd))
    add("fst-lz4", os.path.getsize(d / "wave.lz4.fst"))
    p = o / "zc.fst"
    subprocess.run(["vcd2fst", "-Z", "-c", str(vcd), str(p)], check=True, stdout=subprocess.DEVNULL)
    add("fst-zlib-c", os.path.getsize(p))
    blob = zstandard.ZstdCompressor(level=19).compress(m.bits_sm.tobytes())
    add("bitpack-sm.zst19", len(blob) + len(m.meta_blob(None)), "含信号表")

    lb = F.limbs(m)
    vals = [F._limb_values(m, col, nb) for (_, col, nb) in lb]          # 每段 T 个值

    # C. 我们的方向：一列一个信号段
    for comp, lvl in (("zstd", 3), ("snappy", None)):
        p = o / f"ours_{comp}.parquet"
        tbl = pa.table({"cycle": np.arange(m.T, dtype=np.uint32),
                        **{f"s{j}": v.astype(F._dtype(lb[j][2])) for j, v in enumerate(vals)}})
        pq.write_table(tbl, p, compression=comp, compression_level=lvl)
        back = pq.read_table(p)
        ok = all(np.array_equal(back.column(f"s{j}").to_numpy(), v.astype(F._dtype(lb[j][2]))) for j, v in enumerate(vals))
        add(f"parquet 一列一个信号 ({comp})", os.path.getsize(p) + len(m.meta_blob(None)),
            f"{tbl.num_rows} 行 x {tbl.num_columns} 列；按位宽选整数类型；含信号表", ok)

    # B. vcd2df 的方向：一列一个时间点，无损
    arr = np.stack([v.astype(np.uint64) for v in vals])                 # (段数, T)
    for comp, lvl in (("zstd", 3), ("snappy", None)):
        p = o / f"transposed_{comp}.parquet"
        t0 = time.perf_counter()
        tbl = pa.table({f"#{t}": arr[:, t] for t in range(m.T)})
        pq.write_table(tbl, p, compression=comp, compression_level=lvl)
        dt = time.perf_counter() - t0
        back = pq.read_table(p)
        got = np.stack([back.column(k).to_numpy() for k in back.column_names], axis=1)
        add(f"parquet 一列一个时间点 ({comp})", os.path.getsize(p) + len(m.meta_blob(None)),
            f"{tbl.num_rows} 行 x {tbl.num_columns} 列；uint64；写入 {dt:.1f} 秒；含信号表", bool(np.array_equal(got, arr)))

    # A. 原版 vcd2df
    import pandas as pd  # noqa: F401
    import vcd2df
    txt = open(vcd).read()
    src = vcd
    if "$dumpvars" not in txt:
        # vcd2df 靠 $dumpvars 这一行定位数据开头，Verilator 写的 VCD 没有这一行（没有它 vcd2df 会死循环）。
        # 在 $enddefinitions 之后补一行，不改任何数据。
        src = o / "with_dumpvars.vcd"
        k = txt.index("\n", txt.index("$enddefinitions")) + 1
        open(src, "w").write(txt[:k] + "$dumpvars\n" + txt[k:])
    n_var = sum(1 for line in txt[:txt.index("$enddefinitions")].splitlines() if line.strip().startswith("$var"))
    del txt
    t0 = time.perf_counter()
    try:
        df = vcd2df.vcd2df(str(src))
    except Exception as e:      # 例如 SERV 上超过 63 位的值溢出
        add("vcd2df 1.0 原包", "", f"运行失败：{e!r}"[:200], "不适用")
        df = None
    dt = time.perf_counter() - t0
    for eng_comp in ("snappy", "zstd") if df is not None else ():
        p = o / f"vcd2df_{eng_comp}.parquet"
        df.to_parquet(p, engine="pyarrow", compression=eng_comp)
        add(f"vcd2df 1.0 原包 -> to_parquet ({eng_comp})", os.path.getsize(p),
            f"{df.shape[0]} 行 x {df.shape[1]} 列；VCD 里有 {n_var} 个 $var，它保留 {df.shape[0]} 个（按短名字去重）；"
            f"解析 {dt:.1f} 秒；不是无损，不能和上面几行直接比", "不适用")

    RESULTS.mkdir(exist_ok=True)
    with open(RESULTS / f"vcd2df_{design}.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


if __name__ == "__main__":
    main(sys.argv[1])
