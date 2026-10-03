# 更新日志

本项目遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [1.1.0]

### 新增

- `--color auto|always|never`：彩色输出，默认仅在真实终端上启用，并遵循
  `NO_COLOR` 环境变量。
- 批量转换时的单行进度提示（TTY 上默认开启，可用 `--no-progress` 关闭）。
- 可选 shell 补全：安装 `epubcc[completion]` 后支持 bash / zsh / fish / PowerShell
  的 `argcomplete` 补全。
- PyInstaller 打包配置（`epubcc.spec`）与 GitHub Actions 工作流：跨平台 CI 矩阵、
  Release 时自动构建 sdist/wheel 及 Windows / Linux / macOS 单文件可执行程序。

### 修复

- **Windows 原地转换**：原先在输入 zip 仍打开时就 `os.replace` 覆盖原文件，
  Windows 会因文件被占用而失败；现在先关闭输入再替换输出。
- 临时文件在替换失败时未被清理的问题。

### 改进

- 启动时把标准流切到 UTF-8（`errors="replace"`），避免 Windows 控制台/管道
  因代码页导致 `UnicodeEncodeError`；不支持的终端自动把 `✓/✗/·` 降级为 ASCII。
- PyPI 元数据补全（classifiers、可选依赖、Python 版本范围）。

## [1.0.0]

- 首个版本：EPUB 简繁双向转换，标签感知、保留编码与结构、批量并行、术语表、
  原地转换与备份。
