# 更新日志

本项目遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [1.1.0]

### 新增

- 一键安装脚本：`install.sh`（macOS / Linux）与 `install.bat`（Windows）。
  先检测 Python（未安装或低于 3.9 则拒绝执行），再建独立虚拟环境把 `epubcc`
  装成全局命令并写入 PATH，不污染系统 Python。
- `--color auto|always|never`：彩色输出，默认仅在真实终端上启用，并遵循
  `NO_COLOR` 环境变量。
- 批量转换时的单行进度提示（TTY 上默认开启，可用 `--no-progress` 关闭）。
- 可选 shell 补全：安装 `epubcc[completion]` 后支持 bash / zsh / fish / PowerShell
  的 `argcomplete` 补全。
- PyInstaller 打包配置（`epubcc.spec`）与 GitHub Actions CI：跨平台测试矩阵，
  并在三种系统上验证构建。（本项目不发布到 PyPI，也不提供预编译下载，
  使用者请从源码获取。）

### 修复

- **Windows 原地转换**：原先在输入 zip 仍打开时就 `os.replace` 覆盖原文件，
  Windows 会因文件被占用而失败；现在先关闭输入再替换输出。
- 临时文件在替换失败时未被清理的问题。

### 改进

- 启动时把标准流切到 UTF-8（`errors="replace"`），避免 Windows 控制台/管道
  因代码页导致 `UnicodeEncodeError`；不支持的终端自动把 `✓/✗/·` 降级为 ASCII。
- PyPI 元数据补全（classifiers、可选依赖、Python 版本范围），便于本地打包/安装。

## [1.0.0]

- 首个版本：EPUB 简繁双向转换，标签感知、保留编码与结构、批量并行、术语表、
  原地转换与备份。
