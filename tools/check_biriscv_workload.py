"""独立核对 biRISC-V 负载程序的计算结果。

用法：python tools/check_biriscv_workload.py [设计名，默认 biriscv]
做法：把 tb/biriscv/prog/main.c 用本机 gcc 编成普通程序（加一个打印 sink 写入值的外壳），得到预期序列；
再从波形矩阵里取出数据总线上每一次写 sink 地址的数据，两串逐个比较。
"""
import os
import subprocess
import sys
import tempfile

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from wavebench.common import ROOT, WORK, Matrix  # noqa: E402

design = sys.argv[1] if len(sys.argv) > 1 else "biriscv"
m = Matrix.load(design)


def sig(suffix):
    c = [s for s in m.signals if s["name"].endswith(suffix) or any(a.endswith(suffix) for a in s["aliases"])]
    assert len(c) == 1, (suffix, [s["name"] for s in c])
    s = c[0]
    bits = np.unpackbits(m.bits_sm[s["col"]:s["col"] + s["width"]], axis=1)[:, :m.T].astype(np.uint64)
    w = np.uint64(1) << np.arange(s["width"] - 1, -1, -1, dtype=np.uint64)
    return (bits * w[:, None]).sum(axis=0)


elf = WORK / "build" / "biriscv" / "prog.elf"
nm = subprocess.run(["riscv64-unknown-elf-nm", str(elf)], check=True, capture_output=True, text=True).stdout
addr = int(next(l for l in nm.splitlines() if l.split()[-1] == "sink").split()[0], 16)
wr, a, d = sig("wb_top.mem_d_wr_w"), sig("wb_top.mem_d_addr_w"), sig("wb_top.mem_d_data_wr_w")
hit = np.where((wr != 0) & ((a & ~np.uint64(3)) == addr))[0]
got = [int(x) for x in d[hit]]
# crt0.S 启动时把 .bss 清零，sink 在 .bss 里，所以第一次写入是清零的 0，不是程序结果，去掉
assert got and got[0] == 0, "预期第一次写入是启动代码清零"
got, hit = got[1:], hit[1:]
print(f"sink 地址 0x{addr:08x}；波形里写 sink 共 {len(got)} 次，第一次在周期 {hit[0] if len(hit) else None}，最后一次在周期 {hit[-1] if len(hit) else None}")

# 预期：同一份 main.c 本机编译。把 volatile sink 的每次赋值改成打印（用宏替换，不改源文件）。
src = (ROOT / "tb" / "biriscv" / "prog" / "main.c").read_text(encoding="utf-8")
assert src.count("sink = ") == 2 and "for (;;)" in src
host = ("#include <stdio.h>\nstatic int left;\n" +
        src.replace("volatile unsigned int sink;", "")
           .replace("sink = crc32(buf, 512);", 'printf("%u%c", crc32(buf, 512), 10);')
           .replace("sink = d + a[0];", 'printf("%u%c", d + a[0], 10); if (--left == 0) return 0;')
           .replace("int main(void) {", "int main(void) { left = %d;" % (len(got) // 2 + 2)))
with tempfile.TemporaryDirectory() as td:
    open(os.path.join(td, "h.c"), "w").write(host)
    subprocess.run(["gcc", "-O1", "-fwrapv", "-o", os.path.join(td, "h"), os.path.join(td, "h.c")], check=True)
    exp = [int(x) for x in subprocess.run([os.path.join(td, "h")], check=True, capture_output=True, text=True).stdout.split()]
n = len(got)
ok = n > 0 and got == exp[:n]
print("预期前 6 个:", exp[:6])
print("波形前 6 个:", got[:6])
print(f"比较了 {n} 个值：{'全部相同' if ok else '不同'}")
if not ok:
    for i, (x, y) in enumerate(zip(got, exp)):
        if x != y:
            print(f"第 {i} 个不同：波形 {x}，预期 {y}")
            break
sys.exit(0 if ok else 1)
