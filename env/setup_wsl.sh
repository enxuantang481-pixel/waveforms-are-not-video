#!/usr/bin/env bash
# 在 WSL Ubuntu 里建分析环境。不需要 sudo。
# 用法（在 WSL 里）：bash env/setup_wsl.sh
# 前提（本机已有，apt 装的，需要 sudo 的部分由用户自己装）：
#   verilator iverilog gtkwave(含 vcd2fst/fst2vcd) gcc-riscv64-unknown-elf make git g++ zlib1g-dev
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="${WAVEBENCH_OPT:-$HOME/.local/opt/wavebench}"
mkdir -p "$ROOT"
if [ ! -x "$ROOT/bin/micromamba" ]; then
  # 官方下载地址，见 https://mamba.readthedocs.io/en/latest/installation/micromamba-installation.html
  curl -Ls https://micro.mamba.pm/api/micromamba/linux-64/latest -o "$ROOT/mm.tar.bz2"
  tar -xjf "$ROOT/mm.tar.bz2" -C "$ROOT" bin/micromamba
fi
export PYTHONNOUSERSITE=1   # 不让 ~/.local 里的包混进来
export MAMBA_ROOT_PREFIX="$ROOT/mamba"
if [ ! -d "$MAMBA_ROOT_PREFIX/envs/wavebench" ]; then
  "$ROOT/bin/micromamba" create -y -f "$HERE/environment.yml"
else
  "$ROOT/bin/micromamba" install -y -n wavebench -f "$HERE/environment.yml"
  "$MAMBA_ROOT_PREFIX/envs/wavebench/bin/python" -m pip install pywellen numpy scipy pyarrow duckdb zstandard av matplotlib
fi
ENV="$MAMBA_ROOT_PREFIX/envs/wavebench"
"$ENV/bin/python" -m pip list --format=freeze > "$HERE/pip-freeze.txt"
"$ROOT/bin/micromamba" list -n wavebench > "$HERE/conda-list.txt"
{
  echo "# 系统工具版本（apt 装的）"
  verilator --version
  iverilog -V 2>/dev/null | head -1
  gtkwave --version | head -1
  riscv64-unknown-elf-gcc --version | head -1
  gcc --version | head -1
  "$ENV/bin/ffmpeg" -version | head -1
  "$ENV/bin/zstd" --version
  uname -r
} > "$HERE/tool-versions.txt" 2>&1
echo "环境在 $ENV"
