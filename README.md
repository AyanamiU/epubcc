# epubcc —— EPUB 简繁中文转换命令行工具

用 Python 写的 EPUB 电子书简体 ⇄ 繁体转换命令行工具，底层使用
[OpenCC](https://github.com/BYVoid/OpenCC)。只转换正文文字，尽量不破坏电子书结构。

支持 **Windows / Linux / macOS**。本工具以**源码形式**提供（不发布到 PyPI、
也不提供预编译二进制），需要本机有 Python ≥ 3.9。

## 特性

- **双向转换**：简体 → 繁体、繁体 → 简体，支持大陆 / 台湾 / 香港用词变体
  （`s2t` `s2tw` `s2twp` `s2hk` / `t2s` `tw2s` `tw2sp` `hk2s` 等全部 OpenCC 配置）。
- **自动判断方向**：不指定方向时，自动探测原文是简体还是繁体，再转向另一种。
- **标签感知**：只转换正文文本，以及 `title` / `alt` / `placeholder` 等可读属性；
  自动跳过 `<script>`、`<style>`、HTML 注释、CDATA，以及 `href` / `src` 等
  URL 属性（避免破坏中文文件名链接）。
- **元数据一起改**：`dc:title`、`dc:description`、目录（`toc.ncx` / nav）等都会转换，
  可选 `--update-language` 更新 `dc:language`。
- **保留编码**：识别 BOM、XML 声明、`<meta charset>`，用原编码写回
  （UTF-8 / GBK / Big5 / UTF-16…），不会把整本书统一转成 UTF-8。
- **保留结构**：`mimetype` 仍是第一个且不压缩的条目，图片、字体等二进制文件
  逐字节原样复制，zip 注释与条目顺序保留。
- **批量与并行**：支持目录、`--recursive`、多文件、多线程、`--dry-run`、原地转换
  与 `.bak` 备份。
- **术语表**：可用 JSON 或 TSV 自定义替换（如 软件 → 軟體、人名地名纠正）。
- **友好的终端体验**：彩色输出、批量进度提示、跨平台编码处理
  （Windows 控制台也不会因中文/符号报错），可选 shell 自动补全。

## 安装

需要 Python ≥ 3.9。本工具**只以源码形式提供**（不发布到 PyPI，也不提供预编译
二进制），请先把仓库克隆到本地：

```bash
git clone https://github.com/AyanamiU/epubcc.git epubcc && cd epubcc
```

### 一键安装脚本（推荐）

克隆后，在仓库目录运行对应平台的脚本，即可自动把 `epubcc` 装成全局命令：

```bash
# macOS / Linux
bash install.sh
```

```bat
:: Windows（在 cmd 里执行，或直接双击）
install.bat
```

脚本会：

- 先检查 Python：**未安装或低于 3.9 就直接拒绝执行**；
- 在用户目录建独立虚拟环境，`pip` 安装本仓库（含依赖 OpenCC），不污染系统 Python；
- 把 `epubcc` 命令放进 PATH（macOS/Linux 用软链，Windows 生成 `epubcc.cmd`
  并写入用户 PATH），并在当前终端做一次自检；
- 重跑脚本即可升级 / 重装。

可选环境变量（按需在运行前设置）：

| 变量 | 作用 |
| --- | --- |
| `PYTHON=python3.12` | 指定要用的解释器 |
| `EPUBCC_EXTRAS=detect,completion` | 同时安装可选依赖（chardet / argcomplete） |
| `EPUBCC_VENV=/path` | 自定义隔离环境目录 |
| `EPUBCC_BIN=/path` | 自定义命令安装目录 |
| `EPUBCC_NO_PAUSE=1` | （仅 Windows）结束时不暂停 |

> 脚本就在本仓库里，安装的也是当前这份源码，因此始终是“源码方式”。

### 手动安装（以下任选一种）

如果你不想用脚本，也可以手动执行。下面所有方式都基于克隆到本地的源码。

#### 方式一：直接运行单文件（最简单）

`epubcc.py` 是自包含的单文件脚本，只需要它一个文件即可运行：

```bash
# 只下载这一个文件（无需克隆整个仓库）
curl -fsSLO https://raw.githubusercontent.com/AyanamiU/epubcc/main/epubcc.py
pip install OpenCC                  # 单文件运行需自行安装 OpenCC
python3 epubcc.py --help
python3 epubcc.py -t book.epub
```

或先克隆仓库再运行：

```bash
git clone https://github.com/AyanamiU/epubcc.git epubcc && cd epubcc
pip install OpenCC
python3 epubcc.py -t book.epub
```

想把它变成全局命令，可自行软链（Linux / macOS）：

```bash
chmod +x epubcc.py
ln -sf "$PWD/epubcc.py" ~/.local/bin/epubcc
epubcc --version
```

Windows 上可以建一个 `epubcc.bat` 放进 PATH：

```bat
@echo off
python "%~dp0epubcc.py" %*
```

#### 方式二：安装为命令（从源码 / git）

从本地源码安装：

```bash
cd epubcc                         # 进入已克隆的仓库
pip install .                       # 或 pipx install .
pip install ".[detect]"             # 追加 chardet 编码探测
pip install ".[detect,completion]"  # 再加 shell 补全
```

不克隆、直接从 git 安装也行（pip / pipx 会在临时目录自动拉取源码）：

```bash
pipx install "git+https://github.com/AyanamiU/epubcc.git"
pip  install "git+https://github.com/AyanamiU/epubcc.git"
```

> 注意：`epubcc` **没有发布到 PyPI**，因此 `pip install epubcc` /
> `pipx install epubcc` 不可用，请使用上面的源码 / git 方式。

#### 依赖说明

- `OpenCC`：必需。单文件方式需自行 `pip install OpenCC`；
  用 `pip install .` 安装时会自动装上。
- `chardet`：可选，装后编码探测更准；未安装时退化为
  「BOM / 声明 / UTF-8 / 探测 / gb18030」的顺序兜底。
- `argcomplete`：可选，提供 shell 自动补全。

#### 开启 shell 补全（可选）

先以带 `completion` 的方式安装（`pip install ".[completion]"` 或
`pipx install ".[completion]"`），然后：

```bash
# bash
eval "$(register-python-argcomplete epubcc)"      # 写入 ~/.bashrc
# zsh
autoload -U bashcompinit && bashcompinit
eval "$(register-python-argcomplete epubcc)"      # 写入 ~/.zshrc
# PowerShell
register-python-argcomplete --shell powershell epubcc | Out-String | Invoke-Expression
```

#### 自己打包成可执行文件（可选）

如果确实想要免 Python 的单文件程序，可以自己用仓库里的 `epubcc.spec` 打包
（本机需装 PyInstaller）：

```bash
pip install pyinstaller
pyinstaller epubcc.spec     # 产物在 dist/
```

## 快速开始

> 下面假设你已按上面任一种方式把 `epubcc` 装成了命令。
> 若直接跑源码，把 `epubcc` 换成 `python3 epubcc.py` 即可。

```bash
# 自动判断方向：简体转繁、繁体转简
epubcc book.epub

# 简体 -> 繁体（输出 book_s2t.epub）
epubcc -t book.epub

# 繁体 -> 简体，台湾用词变体
epubcc -s --variant tw book.epub
```

## 用法

```
epubcc [选项] 输入文件或目录 [更多输入...]
```

常用示例：

```bash
# 1. 自动判断方向（简体转繁 / 繁体转简）
epubcc book.epub

# 2. 简体 -> 繁体（输出 book_s2t.epub）
epubcc -t book.epub

# 3. 繁体 -> 简体，台湾用词变体
epubcc -s --variant tw book.epub

# 4. 指定 OpenCC 配置（台湾正体 + 词汇转换）
epubcc -d s2twp book.epub

# 5. 输出到指定目录 / 指定文件
epubcc -t -o out/ book.epub
epubcc -t -o 我的书_繁体.epub book.epub

# 6. 原地转换（生成 book.epub.bak 备份）
epubcc -t -i book.epub
epubcc -t -i --no-backup book.epub

# 7. 批量 / 递归 / 并行
epubcc -t -r -j 4 -o out/ ~/Books/

# 8. 只看统计不写文件
epubcc -t --dry-run book.epub

# 9. 自定义术语表 + 更新语言标记 + 顺便转换 CSS
epubcc -t --glossary terms.tsv --update-language --include-css book.epub

# 10. 彩色输出 / 关闭进度提示
epubcc -t --color always book.epub
epubcc -t --no-progress -r books/
```

### 选项速查

| 选项 | 说明 |
| --- | --- |
| `-t, --to-traditional` | 输出繁体 |
| `-s, --to-simplified` | 输出简体 |
| `-d, --direction NAME` | 直接指定 OpenCC 配置（`auto` 为自动探测，默认） |
| `--variant generic\|tw\|twp\|hk` | 用词变体，配合 `-t` / `-s` 使用 |
| `-o, --output PATH` | 输出目录（无 `.epub` 后缀）或输出文件（`.epub` 后缀） |
| `-i, --in-place` | 原地转换，默认备份为 `*.epub.bak` |
| `--no-backup` | 原地转换时不要备份 |
| `-f, --force` | 覆盖已有输出 / 备份 |
| `-r, --recursive` | 递归处理目录 |
| `--ext .css` | 追加需要转换的扩展名（可重复） |
| `--include-css` | 同时转换 `.css`（默认不动，避免影响字体名） |
| `--raw` | 不做标签感知，整份文本直接转换（慎用） |
| `--no-numeric-entities` | 不转换 `&#x4E2D;` 形式的数字实体 |
| `--glossary FILE` | 术语表（JSON / TSV），可重复 |
| `--update-language` | 同时更新 OPF 里的 `dc:language` |
| `-j, --jobs N` | 并行文件数（默认按 CPU 数） |
| `-n, --dry-run` | 只统计不写出 |
| `-q / -v` | 安静 / 详细输出 |
| `--color auto\|always\|never` | 彩色输出开关（默认 auto，遵循 `NO_COLOR`） |
| `--no-progress` | 关闭批量进度提示 |
| `-V, --version` | 显示版本 |
| `--list-configs` | 列出所有可用 OpenCC 配置 |

### 术语表格式

JSON：

```json
{
  "软件": "軟體",
  "后台": "後台"
}
```

TSV（也支持用空格分隔，`#` 开头的行是注释）：

```
软件	軟體
信息	資訊
```

术语表会在 OpenCC 转换前后各应用一次，所以键写**原文用词**或**目标用词**都能生效，
且整词优先于长词匹配（按长度从长到短替换）。

### 输出文件命名

默认与输入同目录，文件名加上配置后缀：

```
book.epub  ->  book_s2t.epub      （-t）
book.epub  ->  book_t2s.epub      （-s）
book.epub  ->  book_s2twp.epub    （-d s2twp）
book.epub  ->  book_t2s.epub      （自动探测为繁体）
```

## 工作原理

1. 用 `zipfile` 打开 EPUB，逐条目处理，`mimetype` 强制排在第一位且不压缩。
2. 对文本类条目（`.xhtml/.html/.xml/.opf/.ncx/.txt`，可选 `.css`）：
   探测编码 → 解码 → 标签感知地转换 → 用原编码写回。
3. 二进制条目（图片、字体等）原样复制。
4. 先写到同目录的临时文件，输入 zip 关闭后再原子替换输出
   （Windows 上原地覆盖也不会因文件占用失败）。

标签感知的规则：用正则切分「标签」与「标签之间的文本」，
文本部分交给 OpenCC；标签内部只转换白名单属性
（`alt`、`title`、`placeholder`、`aria-label` 等，以及 `<meta name="description">`
的 `content`），`href`/`src` 等 URL 属性一律不动。
`<script>` / `<style>` 的内容、注释与 CDATA 全部保持原样。

## 常见问题

- **Windows 控制台中文乱码或报错？** epubcc 启动时会把标准流切到 UTF-8 并开启
  `errors="replace"`；若仍乱码，可先执行 `chcp 65001` 切换代码页。
- **提示未找到 OpenCC？** 执行 `pip install OpenCC`（手动单文件方式需自行安装；
  用 `install.sh` / `install.bat` 或 `pip install .` 会自动装上）。
- **原地转换失败或提示文件被占用？** 确认没有其他程序（阅读器、编辑器）打开该书，
  再重试；必要时先用 `-f` 覆盖。
- **转换后出现错别字？** OpenCC 是字符/短语级转换，遇到一词多字（如「干」「发」）
  仍可能出错，可用 `--glossary` 词表修正。
- **某些书完全没变？** 极少量 EPUB 把正文放在 `<script>` 里动态生成，默认跳过，
  可用 `--raw` 强制处理（请先备份）。

## 开发

```bash
pip install -e ".[dev]"          # 开发依赖
python -m unittest discover -s tests -v

python -m build                  # 构建 sdist + wheel
pyinstaller epubcc.spec          # 打包单文件可执行程序（产物在 dist/）
```

CI 会在 Ubuntu / Windows / macOS 上跑测试并验证构建，见
`.github/workflows/ci.yml`。本工具不发布到 PyPI，也不提供预编译产物。

## 已知限制

- 极少量 EPUB 把全站文字放在 `<script>` 里动态生成（罕见），默认不会被转换，
  可用 `--raw` 强制处理。
- `--raw` 模式会连标签属性、脚本一起转换，可能破坏链接，请先备份。
- 不做 zip 内文件重命名，因此中文文件名不会被转换（链接因此保持有效）。
- OpenCC 是字符/短语级转换，遇到一词多字（如「干」「发」）仍可能出错，
  可用 `--glossary` 词表修正。

## 许可证

MIT
