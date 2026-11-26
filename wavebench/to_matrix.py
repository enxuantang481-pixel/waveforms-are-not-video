"""用 pywellen 把 VCD / FST 读成规范比特矩阵。

用法：python -m wavebench.to_matrix <设计>
读 wave.vcd、wave.lz4.fst、wave.verilator.fst 三个文件，要求三者读出的矩阵逐位相同，
然后保存 bits_sm.npy 和 signals.json。周期数 T 取自仿真日志（data/<设计>/cycles.txt）。

pywellen 0.25.7 的用法（文档字符串基本是空的，以下是拿真实文件试出来的）：
  w = pywellen.Waveform(path)      VCD 和 FST 都能开
  w.all_vars()                     迭代全部变量；v.full_name()、v.bitwidth()、v.is_real()
  v.signal                         该变量的信号对象；list(signal) 得到 [(时间, 值), ...]，只含变化点
  signal.value_at(t)               t 时刻的值（两态时是 int）
"""
import hashlib
import json
import sys
import time

import numpy as np
import pywellen

from .common import TIME, Matrix, data_dir, sha_bits, to_cycle


def _c(x):
    return x() if callable(x) else x


def changes_to_rows(ch, wd, T):
    """一个信号的变化列表 -> (wd, ceil(T/8)) 的打包比特行（高位在前）。"""
    if ch[0][0] != TIME["t0"]:
        raise ValueError("第一个采样时刻没有值")
    times = to_cycle(np.fromiter((c[0] for c in ch), dtype=np.int64, count=len(ch)))
    if times[-1] >= T:
        raise ValueError("变化时刻超出周期数")
    idx = np.searchsorted(times, np.arange(T), side="right") - 1
    rows = np.empty((wd, (T + 7) // 8), dtype=np.uint8)
    if wd <= 64:
        vals = np.array([c[1] for c in ch], dtype=np.uint64)[idx]
        for i in range(wd):
            rows[i] = np.packbits(((vals >> np.uint64(wd - 1 - i)) & np.uint64(1)).astype(np.uint8))
    else:
        nb = (wd + 7) // 8
        raw = np.frombuffer(b"".join(c[1].to_bytes(nb, "big") for c in ch), dtype=np.uint8).reshape(len(ch), nb)
        ub = np.unpackbits(raw, axis=1)[:, nb * 8 - wd:]
        for i in range(wd):
            rows[i] = np.packbits(ub[idx, i])
    return rows


def read_wave(path, T):
    """返回 (bits_sm, T, signals, 统计)。逐个变量处理，不把全部变化留在内存里。"""
    t0 = time.perf_counter()
    w = pywellen.Waveform(str(path))
    t_open = time.perf_counter() - t0
    seen = {}            # (位宽, 内容哈希) -> 信号下标
    signals, blocks, skipped = [], [], []
    col = n_changes = 0
    for v in _c(w.all_vars):
        name = _c(v.full_name)
        if _c(v.is_real) or _c(v.bitwidth) is None:
            skipped.append(name)
            continue
        wd = int(_c(v.bitwidth))
        ch = list(_c(v.signal))
        for c in ch[:1] + ch[-1:]:
            if not isinstance(c[1], int):
                raise ValueError(f"{name} 出现非两态值 {c[1]!r}")
        rows = changes_to_rows(ch, wd, T)
        key = (wd, hashlib.sha1(rows.tobytes()).digest())
        # 别名：位宽相同且全程取值完全相同的变量并成一个，名字记进别名表（仍然无损）。
        # 这比“同一个底层信号”略宽：恰好全程相等的不同信号也会被并掉。
        if key in seen and np.array_equal(blocks[seen[key]], rows):
            signals[seen[key]]["aliases"].append(name)
            continue
        seen[key] = len(signals)
        signals.append({"name": name, "width": wd, "col": col, "aliases": []})
        blocks.append(rows)
        col += wd
        n_changes += len(ch)
    bits_sm = np.concatenate(blocks)
    stats = {"file": str(path), "format": str(_c(w.file_format)), "t_open_s": t_open,
             "t_total_s": time.perf_counter() - t0, "n_vars": len(signals) + sum(len(s["aliases"]) for s in signals),
             "n_signals": len(signals), "n_changes": n_changes, "skipped": skipped}
    return bits_sm, T, signals, stats


def main(design):
    d = data_dir(design)
    T = int((d / "cycles.txt").read_text())
    ref = None
    allstats = []
    for fn in ("wave.vcd", "wave.lz4.fst", "wave.verilator.fst"):
        bits, T, signals, st = read_wave(d / fn, T)
        st["sha256"] = sha_bits(bits, T)
        st["T"], st["B"] = T, bits.shape[0]
        allstats.append(st)
        print({k: v for k, v in st.items() if k != "skipped"}, "skipped:", len(st["skipped"]), flush=True)
        if ref is None:
            ref = (bits, T, signals)
        else:
            assert bits.shape == ref[0].shape, "形状不同"
            assert np.array_equal(bits, ref[0]), f"{fn} 读出的矩阵和 VCD 的不同"
            assert signals == ref[2], "信号表不同"
        del bits
    m = Matrix(*ref)
    m.save(design, {"read_stats": allstats})
    tog = const = 0
    for b in range(m.B):
        r = m.row(b)
        n = int(np.count_nonzero(r[1:] != r[:-1]))
        tog += n
        const += n == 0
    print(f"OK {design}: T={m.T} B={m.B} 信号={len(m.signals)} 比特翻转总数={tog} 全程不变的比特={const} sha={m.sha()[:16]}")
    (d / "matrix_stats.json").write_text(json.dumps({"T": m.T, "B": m.B, "n_signals": len(m.signals),
                                                      "bit_toggles": tog, "const_bits": const, "read_stats": allstats}))


if __name__ == "__main__":
    main(sys.argv[1])
