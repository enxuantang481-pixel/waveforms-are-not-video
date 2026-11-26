#!/usr/bin/env bash
# 一键重跑：取源码、仿真、读成矩阵、核对、测量全部格式、排序实验、出图出表。
# 在 WSL 里运行：bash scripts/run_all.sh        （三个设计顺序跑，计时互不干扰；全程约 1 到 2 小时）
set -euo pipefail
source "$(dirname "$0")/common.sh"
cd "$WAVEBENCH_ROOT"
bash scripts/fetch_designs.sh
bash scripts/build_tools.sh
declare -A CYC=( [picorv32]=262144 [serv]=262144 [biriscv]=65536 )
for d in picorv32 serv biriscv; do
  bash scripts/build_sim.sh "$d" "${CYC[$d]}"
  python -m wavebench.to_matrix "$d"
  python -m wavebench.vcd_mini "$d" 2048
  rm -f "results/$d.csv"
  python -m wavebench.bench "$d" all   2>&1 | tee "results/$d.all.log"
  python -m wavebench.bench "$d" order 2>&1 | tee "results/$d.order.log"
done
python -m wavebench.plot picorv32 serv biriscv
