#!/usr/bin/env bash
# 克隆三个开源 RISC-V 核到缓存目录，并检出本项目测量时用的提交。
set -euo pipefail
source "$(dirname "$0")/common.sh"
cd "$WAVEBENCH_WORK/src"
fetch() {  # 名字 仓库 提交
  if [ ! -d "$1" ]; then git clone -q "https://github.com/$2.git" "$1"; fi
  git -C "$1" fetch -q --depth 1 origin "$3" 2>/dev/null || true
  git -C "$1" checkout -q "$3"
  echo "$1 $(git -C "$1" rev-parse HEAD)"
}
fetch picorv32 YosysHQ/picorv32      ef203c2b0a3fb793280f5114941416c425c5b461   # ISC
fetch serv     olofk/serv            f200eb2ed7b69ac1c6b8eddd47654522aeee5ce8   # ISC
fetch biriscv  ultraembedded/biriscv 6af9c4be5a0807d368eaad5e49af52322e31d073   # Apache-2.0
