#!/usr/bin/env bash
# 核查（2026-11-26）：空闲复测里 serv_x10 的 Parquet 宽表 zstd -19「取一个信号」走了慢路径
# （首次读取 > 1 秒，只测第一个信号 3 次，中位数 0.33 秒）；第二轮忙时测的是 15 次、0.041 秒。
# 这里重新仿真 serv_x10，把这一个格式（和 zstd -3 对照、进程内 libfst 基准）各测 3 遍，看是不是偶发。
# 结果写到 results/idle_check/，不动 results/idle/。用法：在 WSL 里 bash scripts/check_pq_serv_x10.sh
set -uo pipefail
source "$(dirname "$0")/common.sh"
cd "$WAVEBENCH_ROOT"
export WAVEBENCH_RESULTS="$WAVEBENCH_ROOT/results/idle_check"
mkdir -p "$WAVEBENCH_RESULTS"
LOG="$WAVEBENCH_RESULTS/conditions.log"
cond() { { echo "## $1  $(date -Iseconds)"; echo "loadavg: $(cat /proc/loadavg)"; } >> "$LOG"; }

d=serv_x10
cond start
bash scripts/build_sim.sh serv 2621440 _x10 > "$WAVEBENCH_RESULTS/$d.sim.log" 2>&1 || { echo "sim failed" >> "$LOG"; exit 1; }
python -m wavebench.to_matrix "$d" >> "$WAVEBENCH_RESULTS/$d.sim.log" 2>&1
for k in 1 2 3; do
  cond "round $k"
  python -m wavebench.bench "$d" key parquet-wide >> "$WAVEBENCH_RESULTS/$d.log" 2>&1
  python -m wavebench.bench "$d" inproc fst-lz4   >> "$WAVEBENCH_RESULTS/$d.log" 2>&1
done
rm -rf "$WAVEBENCH_WORK/out/$d" "$WAVEBENCH_WORK/data/$d"
cond end
echo ALL_DONE >> "$LOG"
