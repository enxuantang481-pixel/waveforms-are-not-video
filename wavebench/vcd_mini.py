"""不依赖 wellen 的最小 VCD 解析器，只用来核对 pywellen 读出的矩阵（前 N 个周期）。

只认 Verilator 写出的那种规整 VCD：$scope/$var/$upscope 头部，正文是 #时间、标量 0x/1x、向量 bXXXX 码。
用法：python -m wavebench.vcd_mini <设计> [周期数]
"""
import sys

import numpy as np

from .common import Matrix, data_dir


def parse(path, ncyc):
    scopes, name2code, width = [], {}, {}
    cur = {}
    hist = {}          # code -> [每周期的值]
    t = -1
    with open(path, "r") as f:
        for line in f:
            p = line.split()
            if not p:
                continue
            k = p[0]
            if k == "$scope":
                scopes.append(p[2])
            elif k == "$upscope":
                scopes.pop()
            elif k == "$var":
                code, w, nm = p[3], int(p[2]), p[4]
                name2code[".".join(scopes + [nm])] = code
                width[code] = w
            elif k[0] == "#":
                nt = int(k[1:])
                if t >= 0:
                    for tt in range(t, min(nt, ncyc)):
                        for c in width:
                            hist.setdefault(c, []).append(cur.get(c, 0))
                t = nt
                if t >= ncyc:
                    break
            elif k[0] in "01" and t >= 0:
                cur[k[1:]] = int(k[0])
            elif k[0] == "b" and t >= 0:
                cur[p[1]] = int(k[1:], 2)
    return name2code, width, hist


def main(design, ncyc=4096):
    m = Matrix.load(design)
    name2code, width, hist = parse(data_dir(design) / "wave.vcd", ncyc)
    ok = miss = 0
    for s in m.signals:
        code = name2code.get(s["name"].replace(".[", "["))   # wellen 把数组元素写成 a.[1]
        if code is None:
            miss += 1
            continue
        assert width[code] == s["width"], s["name"]
        vals = hist[code]
        for i in range(s["width"]):
            mine = np.array([(v >> (s["width"] - 1 - i)) & 1 for v in vals], dtype=np.uint8)
            assert np.array_equal(mine, m.row(s["col"] + i)[:ncyc]), f"不一致：{s['name']} 位 {i}"
        ok += 1
    print(f"vcd_mini {design}: 前 {ncyc} 周期，{ok} 个信号逐位一致，{miss} 个按名字没对上（未比较）")
    assert ok > 0 and miss <= 0.05 * len(m.signals)


if __name__ == "__main__":
    main(sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 4096)
