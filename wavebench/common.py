"""路径、计时、规范比特矩阵。

规范矩阵（裁判用的那一份）：bits_sm，形状 (B, ceil(T/8))，uint8。
第 b 行是第 b 个比特在全部 T 个周期上的取值，沿时间轴用 numpy.packbits 打包（高位在前）。
"""
import hashlib
import json
import os
import statistics
import time
from pathlib import Path

import numpy as np

WORK = Path(os.environ.get("WAVEBENCH_WORK", Path.home() / ".cache" / "wavebench"))
ROOT = Path(__file__).resolve().parent.parent
RESULTS = Path(os.environ.get("WAVEBENCH_RESULTS", ROOT / "results"))   # 空闲复测写到 results/idle


# 采样时刻 = t0 + 周期号 × step。基准测量里的波形时间戳就是周期号，恒为 (0, 1)；
# 只有命令行工具（wavebench.cli）读别人的波形时会改成文件里的实际值。
TIME = {"t0": 0, "step": 1}


def to_cycle(times):
    """文件里的时间戳（整数数组）-> 周期号。默认情况下原样返回。"""
    t0, st = TIME["t0"], TIME["step"]
    return times if (t0, st) == (0, 1) else (times - t0) // st


def to_time(c):
    """周期号 -> 文件里的时间戳。"""
    return int(c) if (TIME["t0"], TIME["step"]) == (0, 1) else TIME["t0"] + int(c) * TIME["step"]


def data_dir(design):
    return WORK / "data" / design


def out_dir(design):
    d = WORK / "out" / design
    d.mkdir(parents=True, exist_ok=True)
    return d


class Matrix:
    def __init__(self, bits_sm, T, signals):
        self.bits_sm = bits_sm          # (B, ceil(T/8)) uint8
        self.T = int(T)
        self.B = int(bits_sm.shape[0])
        self.signals = signals          # [{name, width, col, aliases}]

    @staticmethod
    def load(design):
        d = data_dir(design)
        meta = json.loads((d / "signals.json").read_text())
        return Matrix(np.load(d / "bits_sm.npy"), meta["T"], meta["signals"])

    def save(self, design, extra=None):
        d = data_dir(design)
        np.save(d / "bits_sm.npy", self.bits_sm)
        meta = {"T": self.T, "B": self.B, "sha256": self.sha(), "signals": self.signals}
        meta.update(extra or {})
        (d / "signals.json").write_text(json.dumps(meta))

    def sha(self):
        return sha_bits(self.bits_sm, self.T)

    def row(self, b):
        """第 b 个比特的全程，uint8 数组，长度 T。"""
        return np.unpackbits(self.bits_sm[b])[: self.T]

    def tm_chunk(self, c0, c1, order=None):
        """周期 [c0, c1) 的时间优先小块，形状 (c1-c0, B)，取值 0/1。c0 必须是 8 的倍数。"""
        assert c0 % 8 == 0
        sub = self.bits_sm[:, c0 // 8:(c1 + 7) // 8]
        if order is not None:
            sub = sub[order]
        u = np.unpackbits(sub, axis=1)[:, : c1 - c0]
        return np.ascontiguousarray(u.T)

    def column(self, t):
        """周期 t 的全部比特，uint8 数组，长度 B。"""
        return (self.bits_sm[:, t // 8] >> (7 - t % 8)) & 1

    def meta_blob(self, order=None):
        """自制格式要随身带的元数据（名字、位宽、别名、可选的排列），zstd 压缩后的字节。"""
        import zstandard
        m = {"T": self.T, "B": self.B, "signals": self.signals}
        if order is not None:
            m["order"] = [int(x) for x in order]
        return zstandard.ZstdCompressor(level=19).compress(json.dumps(m, separators=(",", ":")).encode())


def sha_bits(bits_sm, T):
    h = hashlib.sha256()
    h.update(f"{bits_sm.shape[0]},{T};".encode())
    h.update(np.ascontiguousarray(bits_sm).tobytes())
    return h.hexdigest()


def pack_sm_from_tm_chunks(chunks, T, B):
    """把一串时间优先的小块（每块 (n, B)，取值 0/1，n 除最后一块外是 8 的倍数）拼回规范矩阵。"""
    out = np.zeros((B, (T + 7) // 8), dtype=np.uint8)
    pos = 0
    for ch in chunks:
        n = ch.shape[0]
        assert pos % 8 == 0
        p = np.packbits(np.ascontiguousarray(ch.T), axis=1)
        out[:, pos // 8: pos // 8 + p.shape[1]] = p
        pos += n
    assert pos == T, (pos, T)
    return out


def timed(fn, reps=3):
    """返回 (最后一次的返回值, 各次耗时秒数列表)。"""
    ts, r = [], None
    for _ in range(reps):
        t0 = time.perf_counter()
        r = fn()
        ts.append(time.perf_counter() - t0)
    return r, ts


def med(ts):
    return statistics.median(ts)


def pick(m, n_sig=5, n_time=5, seed=20261125):
    """固定种子抽样：读法一用的信号下标、读法二用的周期。"""
    rng = np.random.default_rng(seed)
    sig = sorted(int(x) for x in rng.choice(len(m.signals), size=min(n_sig, len(m.signals)), replace=False))
    tim = sorted(int(x) for x in rng.choice(m.T, size=n_time, replace=False))
    return sig, tim


def sig_bits_to_values(bits):
    """(w, T) 的 0/1 数组（高位在前）转成每周期一个值。w<=64 返回 uint64 数组。"""
    w = bits.shape[0]
    assert w <= 64
    v = np.zeros(bits.shape[1], dtype=np.uint64)
    for i in range(w):
        v = (v << np.uint64(1)) | bits[i].astype(np.uint64)
    return v
