# 所有脚本共用的路径。在 WSL 里 source。
export PYTHONNOUSERSITE=1
export WAVEBENCH_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export WAVEBENCH_WORK="${WAVEBENCH_WORK:-$HOME/.cache/wavebench}"
export WAVEBENCH_ENV="${WAVEBENCH_ENV:-$HOME/.local/opt/wavebench/mamba/envs/wavebench}"
export PATH="$WAVEBENCH_ENV/bin:$PATH"
export PYTHONPATH="$WAVEBENCH_ROOT${PYTHONPATH:+:$PYTHONPATH}"
mkdir -p "$WAVEBENCH_WORK"/{src,build,data}
