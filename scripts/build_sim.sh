#!/usr/bin/env bash
# 编译并仿真一个设计，导出 VCD 和 FST（各编一次），再用 vcd2fst 转出几种 FST。
# 用法：bash scripts/build_sim.sh <picorv32|serv|biriscv> [最大周期数] [后缀]
# 给了后缀（如 _x10）时，波形写到 data/<设计><后缀>，用来做不同长度的对比；这时只转默认档 FST。
set -euo pipefail
source "$(dirname "$0")/common.sh"
D="$1"; CYC="${2:-262144}"
TAG="${3:-}"
SRC="$WAVEBENCH_WORK/src"; B="$WAVEBENCH_WORK/build/$D"; OUT="$WAVEBENCH_WORK/data/$D$TAG"
mkdir -p "$B" "$OUT"
TB="$WAVEBENCH_ROOT/tb"
RUNS="${DHRY_RUNS:-100}"

case "$D" in
  picorv32)
    VSRC="$TB/picorv32/wb_top.v $SRC/picorv32/picorv32.v"; VINC=""
    # Dhrystone：仓库自带源码，不依赖 libc（USE_MYSTDLIB=1）
    rm -rf "$B/dhry"; cp -r "$SRC/picorv32/dhrystone" "$B/dhry"
    sed -i "s/Number_Of_Runs = 100;/Number_Of_Runs = $RUNS;/" "$B/dhry/dhry_1.c"
    make -s -C "$B/dhry" dhry.hex USE_MYSTDLIB=1 TOOLCHAIN_PREFIX=riscv64-unknown-elf- \
      CFLAGS="-MD -O3 -mabi=ilp32 -march=rv32im -DTIME -DRISCV -DUSE_MYSTDLIB -ffreestanding -nostdlib -Wno-implicit-int -Wno-implicit-function-declaration"
    cp "$B/dhry/dhry.hex" "$B/dhry.hex" ;;
  serv)
    VSRC="$TB/serv/wb_top.v $SRC/serv/servant/servant.v $SRC/serv/servant/servant_mux.v $SRC/serv/servant/servant_ram.v $SRC/serv/servant/servant_gpio.v $SRC/serv/servant/servant_timer.v $(ls $SRC/serv/servile/*.v) $(ls $SRC/serv/rtl/*.v | grep -v synth_wrapper)"
    VINC="-I$SRC/serv/rtl"
    cp "$SRC/serv/sw/zephyr_hello.hex" "$B/" ;;
  biriscv)
    VSRC="$TB/biriscv/wb_top.v $SRC/biriscv/tb/tb_core_icarus/tcm_mem.v $SRC/biriscv/tb/tb_core_icarus/tcm_mem_ram.v $(ls $SRC/biriscv/src/core/*.v | grep -v -e _defs.v -e xilinx -e trace_sim)"
    VINC="-I$SRC/biriscv/src/core"
    # 仓库自带的 test.elf 只跑约 3 千周期就 $finish，太短；改用本项目自己写的裸机负载 tb/biriscv/prog
    riscv64-unknown-elf-gcc -march=rv32im -mabi=ilp32 -O2 -ffreestanding -nostdlib -fno-builtin       -fno-tree-loop-distribute-patterns -T "$TB/biriscv/prog/link.ld"       "$TB/biriscv/prog/crt0.S" "$TB/biriscv/prog/main.c" -o "$B/prog.elf"
    riscv64-unknown-elf-objcopy -O binary "$B/prog.elf" "$B/tcm.bin"
    python3 - "$B/tcm.bin" "$B/tcm.hex" <<'EOF'
import sys
d = open(sys.argv[1], 'rb').read()
d += b'\0' * (-len(d) % 8)
with open(sys.argv[2], 'w') as f:
    for i in range(0, len(d), 8):
        f.write('%016x\n' % int.from_bytes(d[i:i+8], 'little'))
EOF
    ;;
  *) echo "unknown design $D"; exit 2 ;;
esac

WARN="--unroll-count 4096 --unroll-stmts 1000000 -Wno-fatal -Wno-lint -Wno-style -Wno-WIDTH -Wno-CASEINCOMPLETE -Wno-MULTIDRIVEN -Wno-UNOPTFLAT -Wno-PINMISSING -Wno-TIMESCALEMOD"
for KIND in vcd fst; do
  if [ "$KIND" = fst ]; then TR="--trace-fst"; DEF="-CFLAGS -DTRACE_FST"; else TR="--trace"; DEF=""; fi
  verilator --cc --exe --build -j 8 -O2 $TR $DEF $WARN $VINC --top-module wb_top \
    --Mdir "$B/obj_$KIND" $VSRC "$TB/common/sim_main.cpp" > "$B/verilate_$KIND.log" 2>&1 \
    || { tail -30 "$B/verilate_$KIND.log"; exit 1; }
  ( cd "$B" && /usr/bin/time -f "sim_$KIND wall=%es maxrss=%MKB" "./obj_$KIND/Vwb_top" "$CYC" "$OUT/wave.$KIND" \
      > "$B/sim_$KIND.stdout" 2> "$B/sim_$KIND.log" ) || { tail "$B/sim_$KIND.log"; exit 1; }
  tail -2 "$B/sim_$KIND.log"
done
mv "$OUT/wave.fst" "$OUT/wave.verilator.fst"
grep -o "cycles=[0-9]*" "$B/sim_vcd.log" | cut -d= -f2 > "$OUT/cycles.txt"
# vcd2fst 的几种打包方式（选项见 vcd2fst --help）
t() { /usr/bin/time -f "$1 wall=%es" "${@:2}" 2>&1 | tail -1; }
t fst_lz4      vcd2fst -4 "$OUT/wave.vcd" "$OUT/wave.lz4.fst"
if [ -n "$TAG" ]; then ls -l "$OUT"; exit 0; fi
t fst_fastlz   vcd2fst -F "$OUT/wave.vcd" "$OUT/wave.fastlz.fst"
t fst_zlib     vcd2fst -Z "$OUT/wave.vcd" "$OUT/wave.zlib.fst"
t fst_lz4_c    vcd2fst -4 -c "$OUT/wave.vcd" "$OUT/wave.lz4c.fst"
t fst_zlib_c   vcd2fst -Z -c "$OUT/wave.vcd" "$OUT/wave.zlibc.fst"
ls -l "$OUT"
