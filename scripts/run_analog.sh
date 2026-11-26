#!/usr/bin/env bash
# 第二种数据：SPICE 模拟波形交给音频编码器。用法：bash scripts/run_analog.sh
set -euo pipefail
source "$(dirname "$0")/common.sh"
A="$WAVEBENCH_WORK/analog"; mkdir -p "$A"
for c in ring5 rect buck; do
  if [ ! -f "$A/$c.raw" ]; then
    # 在网表末尾加一段控制脚本，让 ngspice 仿真完把全部点一次写成二进制 rawfile
    # （不用 -r 选项：实测 -r 边仿真边写，配合 .options interp 时文件里的点数和文件头对不上）
    { grep -v '^\.end$' "$WAVEBENCH_ROOT/analog/netlists/$c.cir"; printf '.control
set filetype=binary
run
write %s all
.endc
.end
' "$A/$c.raw"; } > "$A/$c.run.cir"
    ngspice -b "$A/$c.run.cir" > "$A/$c.log" 2>&1 || { tail -20 "$A/$c.log"; exit 1; }
  fi
  python -m wavebench.analog "$c"
done
