"""所有被测格式。每种格式是一个对象，有四个方法：

  encode(m, path)      把规范矩阵写成文件，返回 (文件列表, 命令说明)
  decode_all(m, path)  完整解码回规范矩阵 bits_sm（逐位校验用；m 只提供 T、B、信号表）
  read_signal(m, path, i)  读法一：第 i 个信号的全程，返回 (位宽, T) 的 0/1 数组
  read_time(m, path, t)    读法二：周期 t 的全部比特，返回长度 B 的 0/1 数组

读法函数每次调用都重新打开文件。
"""
import os
import shutil
import re
import subprocess
from pathlib import Path

import numpy as np

from .common import Matrix, data_dir, pack_sm_from_tm_chunks, sig_bits_to_values, to_cycle, to_time

FFMPEG = shutil.which("ffmpeg")
ZSTD = shutil.which("zstd")


def _c(x):
    return x() if callable(x) else x


def _inv(order, B):
    if order is None:
        return None
    inv = np.empty(B, dtype=np.int64)
    inv[order] = np.arange(B)
    return inv


def _canon(bits_perm, order):
    """按排列顺序解出来的矩阵放回规范顺序。"""
    if order is None:
        return bits_perm
    out = np.empty_like(bits_perm)
    out[order] = bits_perm
    return out


# ---------------------------------------------------------------- 对照组：VCD / FST（pywellen 读）

class Wellen:
    family = "control"

    def __init__(self, name, src, tool=None, zst_level=None):
        self.name, self.src, self.tool, self.zst_level = name, src, tool, zst_level
        self.order = None
        self.has_meta = True      # 文件自带名字，不另加元数据

    def encode(self, m, path, design):
        d = data_dir(design)
        if self.zst_level is not None:
            cmd = [ZSTD, f"-{self.zst_level}", "-T1", "-q", "-f", str(d / "wave.vcd"), "-o", str(path)]
            subprocess.run(cmd, check=True)
        elif self.tool:
            cmd = ["vcd2fst", *self.tool, str(d / "wave.vcd"), str(path)]
            pre = d / {"-4": "wave.lz4.fst", "-4-c": "wave.lz4c.fst", "-Z-c": "wave.zlibc.fst"}.get("".join(self.tool), "_none_")
            if (d / "wave.vcd").exists():
                subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL)
            elif pre.exists():
                # 原始 VCD 已按磁盘上限删掉：用仿真当时由同一条命令转出的 FST（见 build_sim.sh），这时编码时间无意义
                shutil.copyfile(pre, path)
                cmd = ["cp", pre.name, "（VCD 已删，沿用同一命令早先转出的文件）"]
            else:
                raise FileNotFoundError("wave.vcd 已删，且没有预先转好的 FST")
        else:
            cmd = ["cp", str(d / self.src), str(path)]
            if Path(path).resolve() != (d / self.src).resolve():
                shutil.copyfile(d / self.src, path)
        return [path], " ".join(Path(c).name if c.startswith("/") else c for c in cmd)

    def _open(self, path):
        import pywellen
        if self.zst_level is not None:
            tmp = str(path) + ".tmp.vcd"
            subprocess.run([ZSTD, "-d", "-q", "-f", str(path), "-o", tmp], check=True)
            w = pywellen.Waveform(tmp)
            return w, tmp
        return pywellen.Waveform(str(path)), None

    def decode_all(self, m, path):
        from .to_matrix import read_wave
        if self.zst_level is not None:
            tmp = str(path) + ".tmp.vcd"
            subprocess.run([ZSTD, "-d", "-q", "-f", str(path), "-o", tmp], check=True)
            bits, T, sigs, _ = read_wave(tmp, m.T)
            os.remove(tmp)
        else:
            bits, T, sigs, _ = read_wave(path, m.T)
        assert T == m.T and [s["name"] for s in sigs] == [s["name"] for s in m.signals]
        return bits

    @staticmethod
    def _expand(ch, wd, T):
        times = to_cycle(np.fromiter((c[0] for c in ch), dtype=np.int64, count=len(ch)))
        idx = np.searchsorted(times, np.arange(T), side="right") - 1
        out = np.empty((wd, T), dtype=np.uint8)
        if wd <= 64:
            vals = np.array([c[1] for c in ch], dtype=np.uint64)[idx]
            for i in range(wd):
                out[i] = (vals >> np.uint64(wd - 1 - i)) & np.uint64(1)
        else:
            for i in range(wd):
                out[i] = np.array([(c[1] >> (wd - 1 - i)) & 1 for c in ch], dtype=np.uint8)[idx]
        return out

    def read_signal(self, m, path, i):
        w, tmp = self._open(path)
        s = m.signals[i]
        for v in _c(w.all_vars):
            if _c(v.full_name) == s["name"]:
                out = self._expand(list(_c(v.signal)), s["width"], m.T)
                break
        if tmp:
            os.remove(tmp)
        return out

    def read_time(self, m, path, t):
        w, tmp = self._open(path)
        want = {s["name"]: s for s in m.signals}
        out = np.zeros(m.B, dtype=np.uint8)
        for v in _c(w.all_vars):
            s = want.pop(_c(v.full_name), None)
            if s is None:
                continue
            val = _c(v.signal).value_at(to_time(t))
            wd = s["width"]
            out[s["col"]: s["col"] + wd] = [(val >> (wd - 1 - k)) & 1 for k in range(wd)]
        assert not want
        if tmp:
            os.remove(tmp)
        return out


# ---------------------------------------------------------------- 对照组：打包比特矩阵 + zstd

class BitpackZstd:
    family = "bitpack"
    has_meta = False

    def __init__(self, major="sm", level=19, order=None, tag=""):
        self.major, self.level, self.order = major, level, order
        self.name = f"bitpack-{major}.zst{level}{tag}"

    def _arr(self, m):
        bits = m.bits_sm if self.order is None else m.bits_sm[self.order]
        if self.major == "sm":
            return bits
        # 时间优先：每个周期一行，沿比特轴打包
        rows = [np.packbits(m.tm_chunk(c0, min(m.T, c0 + 8192), self.order), axis=1) for c0 in range(0, m.T, 8192)]
        return np.concatenate(rows)

    def encode(self, m, path, design):
        import zstandard
        raw = np.ascontiguousarray(self._arr(m)).tobytes()
        Path(path).write_bytes(zstandard.ZstdCompressor(level=self.level).compress(raw))
        return [path], f"numpy.packbits({'信号优先' if self.major == 'sm' else '时间优先'}) + zstandard level={self.level} 单线程"

    def _load(self, m, path):
        import zstandard
        raw = zstandard.ZstdDecompressor().decompress(Path(path).read_bytes())
        if self.major == "sm":
            return np.frombuffer(raw, dtype=np.uint8).reshape(m.B, -1)
        return np.frombuffer(raw, dtype=np.uint8).reshape(m.T, -1)

    def decode_all(self, m, path):
        a = self._load(m, path)
        if self.major == "sm":
            return _canon(a.copy(), self.order)
        chunks = (np.unpackbits(a[c0:c0 + 8192], axis=1)[:, :m.B] for c0 in range(0, m.T, 8192))
        return _canon(pack_sm_from_tm_chunks(chunks, m.T, m.B), self.order)

    def read_signal(self, m, path, i):
        a = self._load(m, path)
        s = m.signals[i]
        cols = np.arange(s["col"], s["col"] + s["width"])
        if self.order is not None:
            cols = _inv(self.order, m.B)[cols]
        if self.major == "sm":
            return np.unpackbits(a[cols], axis=1)[:, :m.T]
        return np.stack([(a[:, c // 8] >> (7 - c % 8)) & 1 for c in cols])

    def read_time(self, m, path, t):
        a = self._load(m, path)
        if self.major == "sm":
            col = (a[:, t // 8] >> (7 - t % 8)) & 1
        else:
            col = np.unpackbits(a[t])[:m.B]
        return _canon(col, self.order)


# ---------------------------------------------------------------- 视频路线

STRIP_W = 1024      # “长图”排法每帧多少个周期
STRIP_HMAX = 4096   # “长图”排法的最大帧高；比特轴更长时切成若干段横向并排放进同一帧


def _band(img, K, H):
    """逻辑图 (n, STRIP_W) -> 帧 (H, K*STRIP_W)：第 k 段（每段 H 行）放在第 k 个横向位置。"""
    buf = np.zeros((K * H, STRIP_W), dtype=np.uint8)
    buf[:img.shape[0], :img.shape[1]] = img
    return np.ascontiguousarray(buf.reshape(K, H, STRIP_W).transpose(1, 0, 2).reshape(H, K * STRIP_W))


def _unband(fr, K, H):
    return fr.reshape(H, K, STRIP_W).transpose(1, 0, 2).reshape(K * H, STRIP_W)
FRAME_W1 = 64       # “每周期一帧”排法，一比特一像素时的帧宽
FRAME_W8 = 32       # 八比特一像素时的帧宽


def _luma(f):
    """取一帧的亮度平面。个别 x264 文件被 PyAV 报成带色度平面的格式，to_ndarray 会多出半帧色度行，这里截掉。"""
    a = f.to_ndarray()
    return a[:f.height] if a.ndim == 2 and a.shape[0] != f.height else a


class Video:
    family = "video"
    has_meta = False

    def __init__(self, codec, layout, bpp=1, order=None, tag="", preset="medium", extra=()):
        self.codec, self.layout, self.bpp, self.order, self.preset = codec, layout, bpp, order, preset
        self.extra = list(extra)
        self.name = f"{codec}{'-' + preset if codec == 'x264' else ''}{''.join(self.extra).replace('-', '_') if extra else ''}-{layout}-{bpp}bpp{tag}"

    def _codec_args(self):
        if self.codec == "ffv1":
            return ["-c:v", "ffv1", "-level", "3", "-g", "1", *self.extra]
        if self.codec == "x264":
            return ["-c:v", "libx264", "-qp", "0", "-preset", self.preset, "-pix_fmt", "gray", *self.extra]
        raise ValueError(self.codec)

    def _geom(self, m):
        n = m.B if self.bpp == 1 else (m.B + 7) // 8      # 比特轴上的像素数
        if self.layout == "frame":
            W = FRAME_W1 if self.bpp == 1 else FRAME_W8
            H = -(-n // W)
            H += H % 2
        else:
            K = -(-n // STRIP_HMAX)
            H = n if K == 1 else STRIP_HMAX
            H += H % 2
            W = K * STRIP_W
        return n, W, H

    def _frames(self, m):
        n, W, H = self._geom(m)
        if self.layout == "frame":
            for c0 in range(0, m.T, 4096):
                ch = m.tm_chunk(c0, min(m.T, c0 + 4096), self.order)
                ch = ch * np.uint8(255) if self.bpp == 1 else np.packbits(ch, axis=1)
                buf = np.zeros((ch.shape[0], W * H), dtype=np.uint8)
                buf[:, :n] = ch
                yield buf.tobytes()
        else:
            for c0 in range(0, m.T, STRIP_W):
                ch = m.tm_chunk(c0, min(m.T, c0 + STRIP_W), self.order).T
                ch = ch * np.uint8(255) if self.bpp == 1 else np.packbits(ch, axis=0)
                yield _band(ch, W // STRIP_W, H).tobytes()

    def encode(self, m, path, design):
        n, W, H = self._geom(m)
        cmd = [FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-f", "rawvideo", "-pix_fmt", "gray",
               "-s", f"{W}x{H}", "-r", "25", "-i", "-", *self._codec_args(), str(path)]
        p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            for buf in self._frames(m):
                p.stdin.write(buf)
            p.stdin.close()
        except BrokenPipeError:
            pass
        err = p.stderr.read().decode(errors="replace")
        if p.wait() != 0:
            raise RuntimeError("ffmpeg 失败: " + err[-400:])
        return [path], "ffmpeg " + " ".join(cmd[1:-1]).replace(str(path), "out.mkv") + f" out.mkv  （帧 {W}x{H}）"

    # --- 解码
    def _to_bits_frame(self, flat, m, n):
        """(k, W*H) 像素 -> (k, B) 比特（排列后的顺序）。"""
        px = flat[:, :n]
        if self.bpp == 1:
            if not np.all((px == 0) | (px == 255)):
                raise ValueError("解码出 0/255 以外的像素值，不是无损")
            return px >> 7
        return np.unpackbits(px, axis=1)[:, :m.B]

    def _to_bits_strip(self, fr, m, n, ncyc):
        """(H, W) 像素 -> (ncyc, B) 比特。"""
        px = _unband(fr, fr.shape[1] // STRIP_W, fr.shape[0])[:n, :ncyc]
        if self.bpp == 1:
            if not np.all((px == 0) | (px == 255)):
                raise ValueError("解码出 0/255 以外的像素值，不是无损")
            return np.ascontiguousarray((px >> 7).T)
        return np.ascontiguousarray(np.unpackbits(px, axis=0)[:m.B].T)

    def _iter(self, path):
        import av
        with av.open(str(path)) as c:
            st = c.streams.video[0]
            st.thread_type = "AUTO"
            for f in c.decode(st):
                yield _luma(f)

    def decode_all(self, m, path):
        n, W, H = self._geom(m)

        def chunks():
            if self.layout == "frame":
                acc = []
                for a in self._iter(path):
                    acc.append(a.reshape(-1))
                    if len(acc) == 4096:
                        yield self._to_bits_frame(np.stack(acc), m, n)
                        acc = []
                if acc:
                    yield self._to_bits_frame(np.stack(acc), m, n)
            else:
                for k, a in enumerate(self._iter(path)):
                    yield self._to_bits_strip(a, m, n, min(STRIP_W, m.T - k * STRIP_W))
        return _canon(pack_sm_from_tm_chunks(chunks(), m.T, m.B), self.order)

    def read_signal(self, m, path, i):
        # 视频解码器不能只解一部分像素：只能整段解码，再取出这个信号所在的像素
        n, W, H = self._geom(m)
        s = m.signals[i]
        cols = np.arange(s["col"], s["col"] + s["width"])
        if self.order is not None:
            cols = _inv(self.order, m.B)[cols]
        px = cols if self.bpp == 1 else np.unique(cols // 8)
        parts = []
        for a in self._iter(path):
            if self.layout == "frame":
                parts.append(a.reshape(-1)[px])
            else:
                parts.append(_unband(a, W // STRIP_W, H)[px])
        if self.layout == "frame":
            arr = np.stack(parts).T                       # (像素数, T)
        else:
            arr = np.concatenate(parts, axis=1)[:, :m.T]
        if self.bpp == 1:
            return arr >> 7
        ub = np.unpackbits(arr, axis=0)                   # 每个像素 8 行
        base = {p: k for k, p in enumerate(px)}
        return np.stack([ub[base[c // 8] * 8 + c % 8] for c in cols])

    def read_time(self, m, path, t):
        import av
        n, W, H = self._geom(m)
        fi = t if self.layout == "frame" else t // STRIP_W
        with av.open(str(path)) as c:
            st = c.streams.video[0]
            target = int(round(fi / st.average_rate / st.time_base))
            c.seek(target, stream=st, backward=True, any_frame=False)
            for f in c.decode(st):
                if f.pts >= target:
                    a = _luma(f)
                    break
        if self.layout == "frame":
            bits = self._to_bits_frame(a.reshape(1, -1), m, n)[0]
        else:
            px = _unband(a, W // STRIP_W, H)[:n, t % STRIP_W]
            bits = (px >> 7) if self.bpp == 1 else np.unpackbits(px)[:m.B]
        return _canon(bits, self.order)


# ---------------------------------------------------------------- 数据表路线

def limbs(m):
    """把每个信号拆成不超过 64 位的段：[(信号下标, 起始列, 位数)]。"""
    out = []
    for i, s in enumerate(m.signals):
        col, rem = s["col"], s["width"]
        first = rem % 64 or 64
        while rem > 0:
            nb = first if rem == s["width"] else 64
            out.append((i, col, nb))
            col += nb
            rem -= nb
    return out


def _dtype(nb):
    return np.uint8 if nb <= 8 else np.uint16 if nb <= 16 else np.uint32 if nb <= 32 else np.uint64


def _limb_values(m, col, nb):
    bits = np.unpackbits(m.bits_sm[col:col + nb], axis=1)[:, :m.T]
    return sig_bits_to_values(bits)


def _vals_to_bits(v, nb):
    v = np.asarray(v).astype(np.uint64)
    return np.stack([((v >> np.uint64(nb - 1 - k)) & np.uint64(1)).astype(np.uint8) for k in range(nb)])


def _wide_arrow(m):
    import pyarrow as pa
    cols = {"cycle": pa.array(np.arange(m.T, dtype=np.uint32))}
    for j, (i, col, nb) in enumerate(limbs(m)):
        cols[f"s{j}"] = pa.array(_limb_values(m, col, nb).astype(_dtype(nb)))
    return pa.table(cols)


def _long_arrow(m):
    import pyarrow as pa
    sig, cyc, val = [], [], []
    for j, (i, col, nb) in enumerate(limbs(m)):
        v = _limb_values(m, col, nb)
        ch = np.flatnonzero(np.concatenate(([True], v[1:] != v[:-1])))
        sig.append(np.full(len(ch), j, dtype=np.uint32))
        cyc.append(ch.astype(np.uint32))
        val.append(v[ch])
    return pa.table({"sig": np.concatenate(sig), "cycle": np.concatenate(cyc), "value": np.concatenate(val)})


def _long_expand(m, sig, cyc, val, want):
    """长表的若干行 -> {段号: T 个值}。输入已按 (sig, cycle) 排序。"""
    out = {}
    for j in want:
        lo, hi = np.searchsorted(sig, j, "left"), np.searchsorted(sig, j, "right")
        idx = np.searchsorted(cyc[lo:hi], np.arange(m.T), side="right") - 1
        out[j] = val[lo:hi][idx]
    return out


class Table:
    family = "table"
    has_meta = False
    order = None

    def __init__(self, engine, shape, level=3, rg=65536):
        self.engine, self.shape, self.level, self.rg = engine, shape, level, rg
        if engine == "parquet":
            self.name = f"parquet-{shape}-zstd{level}-rg{rg}"
        else:
            self.name = f"duckdb-{shape}"

    def encode(self, m, path, design):
        tbl = _wide_arrow(m) if self.shape == "wide" else _long_arrow(m)
        if os.path.exists(path):
            os.remove(path)
        if self.engine == "parquet":
            import pyarrow.parquet as pq
            pq.write_table(tbl, path, compression="zstd", compression_level=self.level, row_group_size=self.rg)
            return [path], (f"pyarrow.parquet.write_table(compression='zstd', compression_level={self.level}, "
                            f"row_group_size={self.rg})，{tbl.num_rows} 行 x {tbl.num_columns} 列")
        import duckdb
        con = duckdb.connect(str(path))
        con.register("src", tbl)
        con.execute("CREATE TABLE w AS SELECT * FROM src")
        con.execute("CHECKPOINT")
        con.close()
        return [path], f"duckdb: CREATE TABLE w AS SELECT * FROM arrow 表; CHECKPOINT，{tbl.num_rows} 行 x {tbl.num_columns} 列"

    # 取若干段的全程值
    def _get_limbs(self, m, path, js):
        if self.shape == "wide":
            names = [f"s{j}" for j in js]
            if self.engine == "parquet":
                import pyarrow.parquet as pq
                t = pq.read_table(path, columns=names)
                return {j: t.column(f"s{j}").to_numpy() for j in js}
            import duckdb
            con = duckdb.connect(str(path), read_only=True)
            r = con.execute(f"SELECT {','.join(names)} FROM w ORDER BY cycle").fetchnumpy()
            con.close()
            return {j: r[f"s{j}"] for j in js}
        if self.engine == "parquet":
            import pyarrow.parquet as pq
            t = pq.read_table(path, filters=[("sig", "in", list(js))])
            sig, cyc, val = (t.column(c).to_numpy() for c in ("sig", "cycle", "value"))
        else:
            import duckdb
            con = duckdb.connect(str(path), read_only=True)
            r = con.execute(f"SELECT sig, cycle, value FROM w WHERE sig IN ({','.join(map(str, js))}) ORDER BY sig, cycle").fetchnumpy()
            con.close()
            sig, cyc, val = r["sig"], r["cycle"], r["value"]
        return _long_expand(m, sig, cyc, val, js)

    def read_signal(self, m, path, i):
        L = limbs(m)
        js = [j for j, l in enumerate(L) if l[0] == i]
        got = self._get_limbs(m, path, js)
        return np.concatenate([_vals_to_bits(got[j], L[j][2]) for j in js])

    def read_time(self, m, path, t):
        L = limbs(m)
        if self.shape == "wide":
            if self.engine == "parquet":
                import pyarrow.parquet as pq
                pf = pq.ParquetFile(path)
                tb = pf.read_row_group(t // self.rg).slice(t % self.rg, 1)
                row = {n: tb.column(n)[0].as_py() for n in tb.column_names}
            else:
                import duckdb
                con = duckdb.connect(str(path), read_only=True)
                cur = con.execute("SELECT * FROM w WHERE cycle = ?", [t])
                row = dict(zip([d[0] for d in cur.description], cur.fetchone()))
                con.close()
            assert row["cycle"] == t
            vals = [row[f"s{j}"] for j in range(len(L))]
        else:
            if self.engine == "parquet":
                import pyarrow.parquet as pq
                tb = pq.read_table(path, filters=[("cycle", "<=", t)])
                sig, val = tb.column("sig").to_numpy(), tb.column("value").to_numpy()
                last = np.concatenate((np.flatnonzero(sig[1:] != sig[:-1]), [len(sig) - 1]))
                assert len(last) == len(L)
                vals = val[last]
            else:
                import duckdb
                con = duckdb.connect(str(path), read_only=True)
                r = con.execute("SELECT sig, arg_max(value, cycle) AS v FROM w WHERE cycle <= ? GROUP BY sig ORDER BY sig", [t]).fetchnumpy()
                con.close()
                assert len(r["sig"]) == len(L)
                vals = r["v"]
        out = np.empty(m.B, dtype=np.uint8)
        for j, (i, col, nb) in enumerate(L):
            v = int(vals[j])
            out[col:col + nb] = [(v >> (nb - 1 - k)) & 1 for k in range(nb)]
        return out

    def decode_all(self, m, path):
        L = limbs(m)
        out = np.zeros((m.B, (m.T + 7) // 8), dtype=np.uint8)
        step = 64
        for a in range(0, len(L), step):
            js = list(range(a, min(len(L), a + step)))
            got = self._get_limbs(m, path, js)
            for j in js:
                _, col, nb = L[j]
                out[col:col + nb] = np.packbits(_vals_to_bits(got[j], nb), axis=1)
        return out


# ---------------------------------------------------------------- 对照组：FST 用 GTKWave 的 C 读取库读（tools/fstq）

class FstNative(Wellen):
    """和 Wellen 写出同样的 FST 文件，但两种读法改用 fstq（libfst）。每次读法起一到两个子进程。"""

    def __init__(self, name, tool):
        super().__init__(name, None, tool=tool)
        from .common import WORK
        self.q = str(WORK / "bin" / "fstq")

    def _handles(self, path):
        out = subprocess.run([self.q, "hier", str(path)], check=True, capture_output=True, text=True).stdout
        h = {}
        for line in out.splitlines():
            hd, _, name = line.split(" ", 2)
            name = name.split(" ")[0]
            h.setdefault(name, []).append(int(hd))
            base = re.sub(r"\[\d+\]$", "", name)      # pywellen 把一位宽数组元素的下标从名字里去掉了
            if base != name:
                h.setdefault(base, []).append(int(hd))
        return h

    @staticmethod
    def _hd(m, h, i):
        """第 i 个信号对应的 FST 句柄列表（高位在前）。pywellen 把一位宽的数组元素并成了一个多位信号，
        实测下标大的是高位；对应错了的话调用方的逐位核对会报错。"""
        s = m.signals[i]
        c = h[s["name"].replace(".[", "[")]
        if len(c) == 1:
            return c
        assert len(c) == s["width"], s["name"]
        return c[::-1]

    def read_signal(self, m, path, i):
        rows = []
        for hd in self._hd(m, self._handles(path), i):
            out = subprocess.run([self.q, "sig", str(path), str(hd)], check=True, capture_output=True, text=True).stdout
            ch = [(int(a), int(b, 2)) for a, b in (ln.split() for ln in out.splitlines())]
            rows.append(self._expand(ch, len(out.split(None, 2)[1]), m.T))
        return rows[0] if len(rows) == 1 else np.concatenate(rows)

    def read_time(self, m, path, t):
        hmap = self._handles(path)
        out = subprocess.run([self.q, "time", str(path), str(to_time(t))], check=True, capture_output=True, text=True).stdout
        val = dict(ln.split() for ln in out.splitlines())
        bits = np.zeros(m.B, dtype=np.uint8)
        for i, s in enumerate(m.signals):
            v = "".join(val[str(hd)] for hd in self._hd(m, hmap, i))
            assert len(v) == s["width"]
            bits[s["col"]: s["col"] + s["width"]] = np.frombuffer(v.encode(), dtype=np.uint8) - 48
        return bits


class FstInproc(FstNative):
    """同样的 FST 文件，用 ctypes 在进程内调 libfst（tools/fstlib.c），不起子进程、不走文本。
    每次读取都重新打开文件并读一遍层次表，和其他格式“每次读取含打开文件”的口径一致。"""
    _lib = None

    @classmethod
    def lib(cls):
        if cls._lib is None:
            import ctypes as C
            from .common import WORK
            L = C.CDLL(str(WORK / "bin" / "libfstq.so"))
            L.fq_open.restype = C.c_void_p
            L.fq_open.argtypes = [C.c_char_p]
            L.fq_close.argtypes = [C.c_void_p]
            L.fq_hier.restype = C.c_char_p
            L.fq_hier.argtypes = [C.c_void_p]
            L.fq_sig.restype = C.c_size_t
            L.fq_sig.argtypes = [C.c_void_p, C.c_uint, C.c_uint, C.POINTER(C.POINTER(C.c_uint64)), C.POINTER(C.POINTER(C.c_ubyte))]
            L.fq_time.argtypes = [C.c_void_p, C.c_uint64, C.c_void_p, C.c_void_p]
            cls._lib = L
        return cls._lib

    def _open_h(self, path):
        L = self.lib()
        ctx = L.fq_open(str(path).encode())
        assert ctx, "fstReaderOpen 失败"
        h, wd = {}, {}
        for line in L.fq_hier(ctx).decode().splitlines():
            hd, w, name = line.split(" ", 2)
            name = name.split(" ")[0]
            wd[int(hd)] = int(w)
            h.setdefault(name, []).append(int(hd))
            base = re.sub(r"\[\d+\]$", "", name)
            if base != name:
                h.setdefault(base, []).append(int(hd))
        return L, ctx, h, wd

    def read_signal(self, m, path, i):
        import ctypes as C
        L, ctx, h, wd = self._open_h(path)
        try:
            rows = []
            for hd in self._hd(m, h, i):
                w = wd[hd]
                tp, vp = C.POINTER(C.c_uint64)(), C.POINTER(C.c_ubyte)()
                n = L.fq_sig(ctx, hd, w, C.byref(tp), C.byref(vp))
                times = to_cycle(np.ctypeslib.as_array(tp, shape=(n,)).astype(np.int64))
                vals = np.ctypeslib.as_array(vp, shape=(n, w)) - np.uint8(48)
                # 同一时刻可能有多条记录（初值加变化），取最后一条
                idx = np.searchsorted(times, np.arange(m.T), side="right") - 1
                rows.append(np.ascontiguousarray(vals[idx].T))
            return rows[0] if len(rows) == 1 else np.concatenate(rows)
        finally:
            L.fq_close(ctx)

    def read_time(self, m, path, t):
        L, ctx, h, wd = self._open_h(path)
        try:
            mx = max(wd)
            off = np.zeros(mx + 2, dtype=np.uint64)
            for hd, w in wd.items():
                off[hd + 1] = w
            off = np.cumsum(off).astype(np.uint64)          # off[hd] 到 off[hd+1] 是句柄 hd 的位置
            out = np.full(int(off[-1]), 48, dtype=np.uint8)
            L.fq_time(ctx, to_time(t), off.ctypes.data, out.ctypes.data)
            out -= 48
            bits = np.zeros(m.B, dtype=np.uint8)
            for i, s in enumerate(m.signals):
                c = s["col"]
                for hd in self._hd(m, h, i):
                    w = wd[hd]
                    bits[c:c + w] = out[int(off[hd]):int(off[hd]) + w]
                    c += w
            return bits
        finally:
            L.fq_close(ctx)
