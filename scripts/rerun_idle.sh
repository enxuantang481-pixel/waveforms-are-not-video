#!/usr/bin/env bash
# 空闲机器复测（2026-11-26）：三个原波形跑全部格式 + 进程内 libfst；两个拉长波形跑关键格式 + 进程内 libfst。
# 结果写到 results/idle/，不覆盖第一、二轮的 CSV。各设计顺序跑，不并行。
# 用法：在 WSL 里 bash scripts/rerun_idle.sh
set -uo pipefail
source "$(dirname "$0")/common.sh"
cd "$WAVEBENCH_ROOT"
export WAVEBENCH_RESULTS="$WAVEBENCH_ROOT/results/idle"
mkdir -p "$WAVEBENCH_RESULTS"
LOG="$WAVEBENCH_RESULTS/conditions.log"

cond() {   # 记录测量条件
  { echo "## $1  $(date -Iseconds)"
    echo "loadavg: $(cat /proc/loadavg)"
    grep -m1 "model name" /proc/cpuinfo
    echo "nproc: $(nproc)  mem: $(free -m | awk '/Mem/{print $2" MB total, "$7" MB available"}')"
    echo "disk(WSL): $(du -sh "$WAVEBENCH_WORK" | cut -f1) in $WAVEBENCH_WORK"
  } >> "$LOG"
}

sha() { python - "$1" <<'EOF'
import sys, hashlib, numpy as np
from wavebench.common import data_dir
a = np.load(data_dir(sys.argv[1]) / "bits_sm.npy")
print(hashlib.sha256(a.tobytes()).hexdigest())
EOF
}

declare -A CYC=( [picorv32]=262144 [serv]=262144 [biriscv]=65536 )
cond "start"
for d in picorv32 serv biriscv; do
  before=$(sha "$d")
  # VCD 第一轮量完删了，重新仿真一次拿回 VCD（仿真是确定性的）
  bash scripts/build_sim.sh "$d" "${CYC[$d]}" > "$WAVEBENCH_RESULTS/$d.sim.log" 2>&1 || { echo "sim $d failed" >> "$LOG"; continue; }
  python -m wavebench.to_matrix "$d" >> "$WAVEBENCH_RESULTS/$d.sim.log" 2>&1
  after=$(sha "$d")
  echo "$d matrix sha256 before=$before after=$after $([ "$before" = "$after" ] && echo SAME || echo DIFFERENT)" >> "$LOG"
  cond "$d all"
  python -m wavebench.bench "$d" all    > "$WAVEBENCH_RESULTS/$d.all.log" 2>&1
  cond "$d inproc"
  python -m wavebench.bench "$d" inproc > "$WAVEBENCH_RESULTS/$d.inproc.log" 2>&1
  rm -f "$WAVEBENCH_WORK/data/$d/wave.vcd"; rm -rf "$WAVEBENCH_WORK/out/$d"
  cond "$d done"
done

for spec in "serv 2621440 _x10" "biriscv 262144 _x4"; do
  set -- $spec; d="$1$3"
  bash scripts/build_sim.sh "$1" "$2" "$3" > "$WAVEBENCH_RESULTS/$d.sim.log" 2>&1 || { echo "sim $d failed" >> "$LOG"; continue; }
  python -m wavebench.to_matrix "$d" >> "$WAVEBENCH_RESULTS/$d.sim.log" 2>&1
  cond "$d key"      # VCD 留到测完：FST 最小档要从它现转
  python -m wavebench.bench "$d" key    > "$WAVEBENCH_RESULTS/$d.key.log" 2>&1
  cond "$d inproc"
  python -m wavebench.bench "$d" inproc > "$WAVEBENCH_RESULTS/$d.inproc.log" 2>&1
  rm -rf "$WAVEBENCH_WORK/out/$d" "$WAVEBENCH_WORK/data/$d"
  cond "$d done"
done
cond "end"
echo ALL_DONE >> "$LOG"
