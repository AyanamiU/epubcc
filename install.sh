#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# epubcc 一键安装脚本（macOS / Linux）
#
# 用法：先安装好 Python（>= 3.9），然后在仓库目录执行：
#     bash install.sh
#
# 可选环境变量：
#     PYTHON=python3.12            指定要用的解释器
#     EPUBCC_EXTRAS=detect,completion   同时安装可选依赖
#     EPUBCC_VENV=/path/to/venv    自定义隔离环境目录
#     EPUBCC_BIN=/path/to/bin      自定义命令安装目录
#
# 脚本会：检查 Python -> 建隔离 venv -> pip 安装本仓库 -> 把 epubcc
# 链接进一个在 PATH 里的目录。没有 Python 时直接拒绝执行。
# ---------------------------------------------------------------------------
set -euo pipefail

# ---- 输出小工具 --------------------------------------------------------- #
if [ -t 1 ] && [ -z "${NO_COLOR:-}" ]; then
    _c() { printf '\033[%sm%s\033[0m' "$1" "$2"; }
else
    _c() { printf '%s' "$2"; }
fi
info() { printf '%s %s\n' "$(_c 32 '==>')" "$*"; }
warn() { printf '%s %s\n' "$(_c 33 '警告:')" "$*" >&2; }
die()  { printf '%s %s\n' "$(_c 31 '错误:')" "$*" >&2; exit 1; }

# ---- 定位仓库目录 ------------------------------------------------------- #
SCRIPT_PATH="${BASH_SOURCE[0]:-$0}"
SRC_DIR="$(cd "$(dirname "$SCRIPT_PATH")" && pwd)"
[ -f "$SRC_DIR/epubcc.py" ] || \
    die "在 $SRC_DIR 里找不到 epubcc.py，请在 epubcc 仓库目录中运行本脚本。"

# ---- 1. 检查 Python ----------------------------------------------------- #
find_python() {
    if [ -n "${PYTHON:-}" ]; then
        command -v "$PYTHON" >/dev/null 2>&1 && { printf '%s' "$PYTHON"; return 0; }
        return 1
    fi
    local c
    for c in python3 python; do
        if command -v "$c" >/dev/null 2>&1; then
            printf '%s' "$c"
            return 0
        fi
    done
    return 1
}

PY="$(find_python)" || die "未检测到 Python。请先安装 Python 3.9 或更高版本后重试：
      https://www.python.org/downloads/
      macOS 也可用：brew install python
      Debian/Ubuntu：sudo apt install python3 python3-venv"

"$PY" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 9) else 1)' || \
    die "检测到的 $("$PY" --version 2>&1) 低于 3.9，请升级后重试。"

info "使用 $("$PY" --version 2>&1)（$(command -v "$PY")）"

# ---- 2. 建隔离虚拟环境 -------------------------------------------------- #
VENV_DIR="${EPUBCC_VENV:-$HOME/.local/share/epubcc/venv}"
SPEC="$SRC_DIR"
[ -n "${EPUBCC_EXTRAS:-}" ] && SPEC="${SRC_DIR}[${EPUBCC_EXTRAS}]"

info "创建隔离环境：$VENV_DIR"
"$PY" -m venv "$VENV_DIR" 2>/dev/null || \
    die "创建虚拟环境失败。Debian/Ubuntu 可能需要：sudo apt install python3-venv"

info "安装 epubcc（含依赖 OpenCC，首次需要联网）…"
"$VENV_DIR/bin/python" -m pip install --quiet --upgrade pip || \
    warn "升级 pip 失败，继续尝试安装…"
"$VENV_DIR/bin/python" -m pip install --quiet --upgrade "$SPEC" || \
    die "安装失败，请检查网络后重试。"

# ---- 3. 安装命令到 PATH ------------------------------------------------- #
pick_bin_dir() {
    local d
    if [ -n "${EPUBCC_BIN:-}" ]; then
        mkdir -p "$EPUBCC_BIN" 2>/dev/null || return 1
        printf '%s' "$EPUBCC_BIN"
        return 0
    fi
    for d in "$HOME/.local/bin" "/usr/local/bin"; do
        [ -n "$d" ] || continue
        if [ -d "$d" ] && [ -w "$d" ]; then
            printf '%s' "$d"
            return 0
        fi
    done
    if mkdir -p "$HOME/.local/bin" 2>/dev/null; then
        printf '%s' "$HOME/.local/bin"
        return 0
    fi
    return 1
}

BIN_DIR="$(pick_bin_dir)" || die "找不到可写的命令目录，可设置 EPUBCC_BIN 指定一个目录。"
ln -sf "$VENV_DIR/bin/epubcc" "$BIN_DIR/epubcc"
info "已安装命令：$BIN_DIR/epubcc"

case ":$PATH:" in
    *":$BIN_DIR:"*) ;;
    *)
        warn "$BIN_DIR 不在当前 PATH 中。请把下面一行加入 ~/.bashrc 或 ~/.zshrc："
        printf '\n    export PATH="%s:$PATH"\n\n' "$BIN_DIR"
        ;;
esac

# ---- 4. 验证 ------------------------------------------------------------ #
if "$BIN_DIR/epubcc" --version >/dev/null 2>&1; then
    info "安装完成：$("$BIN_DIR/epubcc" --version)"
    case ":$PATH:" in
        *":$BIN_DIR:"*) printf '\n现在可以直接使用，例如：  epubcc -t 一本书.epub\n' ;;
        *) printf '\n重开终端（或先执行上面的 export）后即可使用：  epubcc -t 一本书.epub\n' ;;
    esac
else
    die "安装后自检失败，请检查上面的输出。"
fi
