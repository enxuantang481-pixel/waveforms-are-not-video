"""第二种数据：SPICE 模拟波形交给音频编码器。

用法：python -m wavebench.analog <电路名>      （先由 scripts/run_analog.sh 用 ngspice 生成 <电路名>.raw）

规范内容：float32 矩阵 X，形状 (信号数, 采样点数)，均匀时间步（网表里开了 .options interp）。
注意 ngspice 输出的是 float64，这里先统一降成 float32（音频编码器存不了 float64），
所有格式都是对同一份 float32 内容做比较，“无损”指的是和这份 float32 逐位相同。
"""
import csv
import hashlib
import os
import subprocess
import sys
import time

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import zstandard

from .common import RESULTS, WORK, med

FFMPEG = "ffmpeg"
A = WORK / "analog"


def read_raw(path):
    """读 ngspice 二进制 rawfile（实数）。返回 (变量名列表, float64 数组 (点数, 变量数))。"""
    b = open(path, "rb").read()
    k = b.index(b"Binary:\n")
    head = b[:k].decode(errors="replace").splitlines()
    nv = int(next(l for l in head if l.startswith("No. Variables")).split(":")[1])
    npt = int(next(l for l in head if l.startswith("No. Points")).split(":")[1])
    flags = next(l for l in head if l.startswith("Flags"))
    assert "real" in flags, flags
    i = head.index("Variables:")
    names = [head[i + 1 + j].split()[1] for j in range(nv)]
    data = np.frombuffer(b, dtype="<f8", count=nv * npt, offset=k + len(b"Binary:\n")).reshape(npt, nv)
    return names, data


def timed(fn, n=3):
    ts, r = [], None
    for _ in range(n):
        t0 = time.perf_counter()
        r = fn()
        ts.append(time.perf_counter() - t0)
        if ts[0] > 20:
            break
    return r, med(ts), len(ts)


def ff(args, data=None):
    p = subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y", *args], input=data, capture_output=True)
    if p.returncode:
        raise RuntimeError(p.stderr.decode(errors="replace")[-300:])
    return p.stdout


def shuffle(x):          # 把 float32 的四个字节拆成四个平面
    return np.ascontiguousarray(x.view(np.uint8).reshape(-1, 4).T).tobytes()


def unshuffle(b, shape):
    return np.ascontiguousarray(np.frombuffer(b, dtype=np.uint8).reshape(4, -1).T).view("<f4").reshape(shape)


def main(name):
    names, d = read_raw(A / f"{name}.raw")
    t = d[:, 0]
    dt = np.diff(t)
    uniform = bool(np.allclose(dt, np.median(dt), rtol=1e-3, atol=0))
    X = np.ascontiguousarray(d[:, 1:].T.astype("<f4"))          # (S, N)
    S, N = X.shape
    sha = hashlib.sha256(X.tobytes()).hexdigest()
    f64_err = float(np.max(np.abs(X.astype(np.float64) - d[:, 1:].T) / (np.max(np.abs(d[:, 1:].T), axis=1, keepdims=True) + 1e-300)))
    swing = (X.max(axis=1) - X.min(axis=1)).tolist()
    print(f"{name}: 各信号摆幅 {dict(zip(names[1:], [round(float(v), 4) for v in swing]))}")
    print(f"{name}: 信号 {S} 个，采样点 {N}，时间步均匀={uniform}，float32 相对满幅最大误差={f64_err:.2e}，sha={sha[:16]}", flush=True)
    out = A / name
    out.mkdir(exist_ok=True)
    rows = []

    def rec(fmt, path, enc, dec, lossless, note="", cmd=""):
        (_, te, ne) = enc
        (Y, td, nd) = dec
        ok = Y.shape == X.shape and Y.tobytes() == X.tobytes()
        err = float(np.max(np.abs(Y.astype(np.float64) - X) / (np.max(np.abs(X), axis=1, keepdims=True).astype(np.float64) + 1e-300)))
        r = dict(circuit=name, S=S, N=N, format=fmt, size_bytes=os.path.getsize(path), bit_exact=ok, claimed_lossless=lossless,
                 max_err_rel_fullscale=err, enc_s_med=te, enc_n=ne, dec_s_med=td, dec_n=nd, loadavg=os.getloadavg()[0],
                 command=cmd, note=note)
        rows.append(r)
        print(f"{fmt:28s} {r['size_bytes']:>11} 逐位相同={ok} 最大相对误差={err:.2e} enc={te:.3f}s dec={td:.3f}s {note}", flush=True)

    # 1) 原始 float32
    p = out / "raw.f32"
    rec("raw-f32", p, timed(lambda: p.write_bytes(X.tobytes())), timed(lambda: np.fromfile(p, dtype="<f4").reshape(S, N)), True)
    # 2) zstd
    for lvl in (3, 19):
        p = out / f"f32.zst{lvl}"
        rec(f"f32.zst{lvl}", p, timed(lambda: p.write_bytes(zstandard.ZstdCompressor(level=lvl, threads=-1).compress(X.tobytes()))),
            timed(lambda: np.frombuffer(zstandard.ZstdDecompressor().decompress(p.read_bytes()), dtype="<f4").reshape(S, N)), True)
    p = out / "f32.shuf.zst19"
    rec("f32.byteshuffle.zst19", p, timed(lambda: p.write_bytes(zstandard.ZstdCompressor(level=19, threads=-1).compress(shuffle(X)))),
        timed(lambda: unshuffle(zstandard.ZstdDecompressor().decompress(p.read_bytes()), (S, N))), True, "四个字节平面分开后再压")
    # 3) Parquet：每个信号一列
    tb = pa.table({f"s{i}": X[i] for i in range(S)})
    for tag, kw in (("plain", dict(use_dictionary=False)),
                    ("bss", dict(use_dictionary=False, use_byte_stream_split=True))):
        p = out / f"{tag}.parquet"
        rec(f"parquet-f32-{tag}-zstd3", p, timed(lambda: pq.write_table(tb, p, compression="zstd", compression_level=3, **kw)),
            timed(lambda: np.stack([c.to_numpy() for c in pq.read_table(p).columns])), True,
            "BYTE_STREAM_SPLIT 编码" if tag == "bss" else "")
    # 4) WavPack 浮点（无损）：全部信号首尾相接成一条单声道
    p = out / "all.wv"
    cmd = ["-f", "f32le", "-ar", "48000", "-ac", "1", "-i", "-", "-c:a", "wavpack", "-compression_level", "3", str(p)]
    dcmd = ["-i", str(p), "-f", "f32le", "-c:a", "pcm_f32le", "-"]
    rec("wavpack-float", p, timed(lambda: ff(cmd, X.tobytes())),
        timed(lambda: np.frombuffer(ff(dcmd), dtype="<f4").reshape(S, N)), True, "",
        "ffmpeg -f f32le -ar 48000 -ac 1 -i - -c:a wavpack -compression_level 3 out.wv")
    # 5) FLAC 24 位（有损：每个信号按自己的最大幅值量化到 24 位整数）
    scale = np.max(np.abs(X), axis=1, keepdims=True).astype(np.float64)
    scale[scale == 0] = 1.0
    q = np.round(X / scale * (2 ** 23 - 1)).astype("<i4")
    p = out / "all.flac"
    cmd = ["-f", "s32le", "-ar", "48000", "-ac", "1", "-i", "-", "-c:a", "flac", "-compression_level", "8", "-sample_fmt", "s32", str(p)]
    dcmd = ["-i", str(p), "-f", "s32le", "-c:a", "pcm_s32le", "-"]

    def unq():
        z = np.frombuffer(ff(dcmd), dtype="<i4").reshape(S, N)
        return ((z >> 8).astype(np.float64) / (2 ** 23 - 1) * scale).astype("<f4")
    rec("flac-24bit", p, timed(lambda: ff(cmd, (q << 8).tobytes())), timed(unq), False,
        "有损：24 位量化；每个信号另存一个幅值（没计入体积，共 %d 字节）" % (8 * S),
        "ffmpeg -f s32le -ar 48000 -ac 1 -i - -c:a flac -compression_level 8 -sample_fmt s32 out.flac")
    # 6) 同样的 24 位整数用 zstd，给 FLAC 一个公平的对照
    p = out / "q24.zst19"
    q3 = np.ascontiguousarray(q.view(np.uint8).reshape(-1, 4)[:, :3])
    rec("q24.zst19", p, timed(lambda: p.write_bytes(zstandard.ZstdCompressor(level=19, threads=-1).compress(q3.tobytes()))),
        timed(lambda: _q24(p, S, N, scale)), False, "有损：同样的 24 位量化后直接 zstd")

    RESULTS.mkdir(exist_ok=True)
    f = RESULTS / "analog.csv"
    new = not f.exists()
    with open(f, "a", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        if new:
            w.writeheader()
        w.writerows(rows)
    import shutil
    shutil.rmtree(out)


def _q24(p, S, N, scale):
    b = np.frombuffer(zstandard.ZstdDecompressor().decompress(p.read_bytes()), dtype=np.uint8).reshape(-1, 3)
    z = np.zeros((b.shape[0], 4), dtype=np.uint8)
    z[:, :3] = b
    z[:, 3] = np.where(b[:, 2] & 0x80, 255, 0)
    return (z.view("<i4").reshape(S, N).astype(np.float64) / (2 ** 23 - 1) * scale).astype("<f4")


if __name__ == "__main__":
    main(sys.argv[1])
