#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""epubcc —— EPUB 电子书简繁中文转换命令行工具。

基于 OpenCC 在 EPUB 内部逐文件转换中文文本，支持：

* 简体 ⇄ 繁体（大陆 / 台湾 / 香港用词变体）
* 自动判断方向（`--direction auto`，默认）
* 标签感知：只转换正文文本与可读属性，跳过 `<script>`/`<style>`、
  注释、CDATA、URL/路径属性，图片、字体等二进制资源原样保留
* 保留原有文件编码（UTF-8 / GBK / Big5 / UTF-16 …）
* 保留 EPUB 结构（`mimetype` 必须是第一个且不压缩的条目）
* 批量 / 目录 / 递归 / 原地转换 / 备份 / 并行 / 自定义术语表

典型用法::

    epubcc book.epub                        # 自动判断方向
    epubcc -t book.epub                     # 简体 -> 繁体
    epubcc -s --variant tw book.epub        # 台湾正体 -> 简体
    epubcc -t -o out/ books/                # 批量输出到目录
    epubcc -t -i book.epub                  # 原地转换，生成 book.epub.bak
"""

from __future__ import annotations

import argparse
import codecs
import concurrent.futures
import copy
import json
import os
import re
import shutil
import sys
import tempfile
import threading
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Sequence

__version__ = "1.1.0"
PROG = "epubcc"

try:
    from opencc import OpenCC
except ImportError:  # pragma: no cover
    sys.stderr.write("错误: 未找到 OpenCC，请先安装：pip install OpenCC\n")
    raise SystemExit(2)

try:  # 可选：shell 自动补全（pip install epubcc[completion]）
    import argcomplete
except ImportError:  # pragma: no cover
    argcomplete = None  # type: ignore[assignment]


# --------------------------------------------------------------------------- #
# 常量
# --------------------------------------------------------------------------- #

#: OpenCC 全部可用配置
OPENCC_CONFIGS = (
    "s2t", "s2tw", "s2twp", "s2hk",
    "t2s", "tw2s", "tw2sp", "hk2s",
    "t2tw", "tw2t", "t2hk", "hk2t", "t2jp", "jp2t",
)

#: (方向, 变体) -> OpenCC 配置
VARIANTS: dict[tuple[str, str], str] = {
    ("t", "generic"): "s2t",
    ("t", "tw"): "s2tw",
    ("t", "twp"): "s2twp",
    ("t", "hk"): "s2hk",
    ("s", "generic"): "t2s",
    ("s", "tw"): "tw2s",
    ("s", "twp"): "tw2sp",
    ("s", "hk"): "hk2s",
}

#: 目标语言 -> OPF 中的 dc:language 建议值
LANG_TAGS = {
    ("t", "generic"): "zh-Hant",
    ("t", "tw"): "zh-TW",
    ("t", "twp"): "zh-TW",
    ("t", "hk"): "zh-HK",
    ("s", "generic"): "zh-Hans",
    ("s", "tw"): "zh-CN",
    ("s", "twp"): "zh-CN",
    ("s", "hk"): "zh-Hans",
}

#: 默认参与转换的扩展名
DEFAULT_TEXT_EXTS = frozenset(
    {".html", ".htm", ".xhtml", ".xht", ".xml", ".opf", ".ncx", ".txt", ".md"}
)

#: 用于方向探测/文本统计的扩展名
_SAMPLE_EXTS = frozenset(
    {".html", ".htm", ".xhtml", ".xht", ".xml", ".opf", ".ncx", ".txt"}
)

#: 不转换、但需要跨标签识别其内容的原始文本元素
_RAW_ELEMENTS = frozenset({"script", "style"})

#: 文本型属性白名单（URL/路径类属性永不转换，避免破坏链接）
_ATTR_WHITELIST = frozenset(
    {"alt", "title", "placeholder", "aria-label", "aria-description",
     "abbr", "summary", "label", "caption", "tooltip", "data-title"}
)

#: <meta content="..."> 中允许转换的 name/property
_META_TEXT_KEYS = frozenset(
    {"description", "keywords", "og:title", "og:description",
     "twitter:title", "twitter:description", "dc.title", "dc.description"}
)

#: 匹配注释 / CDATA / 标签
_MARKUP_RE = re.compile(r"<!--.*?-->|<!\[CDATA\[.*?\]\]>|<[^<>]*>", re.S)

#: 从标签中提取元素名（支持 </script>）
_TAG_NAME_RE = re.compile(r"<\s*/?\s*([A-Za-z][-A-Za-z0-9_:.]*)")

#: 属性 name="value" / name='value'
_ATTR_RE = re.compile(r"""([A-Za-z_:][-A-Za-z0-9_:.]*)\s*=\s*(?:"([^"]*)"|'([^']*)')""")

#: 数字字符引用 &#123; / &#x4E2D;
_NUMERIC_ENTITY_RE = re.compile(r"&#(?:[xX]([0-9A-Fa-f]+)|(\d+));")

_XML_DECL_RE = re.compile(
    rb"""<\?xml[^>]*?encoding\s*=\s*["']\s*([A-Za-z0-9_.:+-]+)\s*["']""", re.I
)
_META_CHARSET_RE = re.compile(
    rb"""<meta[^>]*?charset\s*=\s*["']?\s*([A-Za-z0-9_.:+-]+)""", re.I
)
_DC_LANGUAGE_RE = re.compile(
    r"(<dc:language\b[^>]*>)([^<]*)(</dc:language\s*>)", re.I
)

_BOMS: tuple[tuple[bytes, str], ...] = (
    (codecs.BOM_UTF32_LE, "utf-32"),
    (codecs.BOM_UTF32_BE, "utf-32"),
    (codecs.BOM_UTF8, "utf-8-sig"),
    (codecs.BOM_UTF16_LE, "utf-16"),
    (codecs.BOM_UTF16_BE, "utf-16"),
)


class ConvertError(Exception):
    """转换过程中出现的可预期错误。"""


# --------------------------------------------------------------------------- #
# OpenCC 与文本转换
# --------------------------------------------------------------------------- #

_tls = threading.local()


def get_opencc(config: str) -> OpenCC:
    """按线程缓存 OpenCC 实例（OpenCC 对象不是线程安全的）。"""
    cache: dict[str, OpenCC] = getattr(_tls, "cache", None)  # type: ignore[assignment]
    if cache is None:
        cache = _tls.cache = {}  # type: ignore[assignment]
    if config not in cache:
        cache[config] = OpenCC(config)
    return cache[config]


def diff_count(a: str, b: str) -> int:
    """粗略统计两段文本之间变化的字符数。"""
    if a == b:
        return 0
    return sum(1 for x, y in zip(a, b) if x != y) + abs(len(a) - len(b))


def config_direction(config: str) -> str:
    """根据配置名推断目标方向：'t'（繁体）或 's'（简体）。"""
    return "s" if config.startswith("t") or config.startswith(("tw", "hk", "jp")) else "t"


def infer_variant(config: str) -> str:
    """从 OpenCC 配置名推断用词变体：tw / hk / generic。"""
    if "tw" in config:
        return "tw"
    if "hk" in config:
        return "hk"
    return "generic"


class TextConverter:
    """封装 OpenCC + 术语表 + 数字实体处理。"""

    def __init__(
        self,
        config: str,
        glossary: Sequence[tuple[str, str]] = (),
        entities: bool = True,
    ) -> None:
        self.oc = get_opencc(config)
        self.glossary = list(glossary)
        self.entities = entities

    def convert(self, text: str) -> tuple[str, int]:
        if not text:
            return text, 0
        # 术语表在转换前后各应用一次：写原文用词或目标用词都能生效
        out = self._apply(text)
        out = self.oc.convert(out)
        out = self._apply(out)
        if self.entities and "&#" in out:
            out = _NUMERIC_ENTITY_RE.sub(self._convert_entity, out)
        return out, diff_count(text, out)

    def _apply(self, text: str) -> str:
        for src, dst in self.glossary:
            if src in text:
                text = text.replace(src, dst)
        return text

    def _convert_entity(self, m: re.Match[str]) -> str:
        if m.group(1) is not None:
            ch = chr(int(m.group(1), 16))
        else:
            ch = chr(int(m.group(2)))
        new = self.oc.convert(self._apply(ch))
        if new == ch:
            return m.group(0)
        return "".join("&#x%X;" % ord(c) for c in new)


def _get_attr(tag: str, name: str) -> str | None:
    m = re.search(
        r"""\b%s\s*=\s*(?:"([^"]*)"|'([^']*)')""" % re.escape(name), tag, re.I
    )
    if not m:
        return None
    return m.group(1) if m.group(1) is not None else m.group(2)


def _convert_tag(tag: str, tc: TextConverter, elem: str | None) -> tuple[str, int]:
    """转换标签内白名单属性的取值（保留引号与其它内容原样）。"""
    if not elem:
        return tag, 0
    changed = 0

    def repl(m: re.Match[str]) -> str:
        nonlocal changed
        name = m.group(1)
        quoted = m.group(2)
        value = quoted if quoted is not None else m.group(3)
        quote = '"' if quoted is not None else "'"
        lname = name.lower()
        if lname not in _ATTR_WHITELIST and not (elem == "meta" and lname == "content"):
            return m.group(0)
        if elem == "meta" and lname == "content":
            key = (_get_attr(tag, "name") or _get_attr(tag, "property") or "").lower()
            if key not in _META_TEXT_KEYS:
                return m.group(0)
        new, n = tc.convert(value or "")
        if n == 0:
            return m.group(0)
        changed += n
        return f"{name}={quote}{new}{quote}"

    return _ATTR_RE.sub(repl, tag), changed


def convert_document(tc: TextConverter, text: str, raw: bool = False) -> tuple[str, int]:
    """转换一份 HTML/XHTML/XML/CSS 文本，返回 (新文本, 变化字符数)。"""
    if raw:
        return tc.convert(text)

    out: list[str] = []
    pos = 0
    in_raw = False
    changed = 0
    for m in _MARKUP_RE.finditer(text):
        if m.start() > pos:
            chunk = text[pos:m.start()]
            if in_raw:
                out.append(chunk)
            else:
                new, n = tc.convert(chunk)
                changed += n
                out.append(new)

        tag = m.group(0)
        closing = tag.startswith("</")
        name_m = _TAG_NAME_RE.match(tag)
        elem = name_m.group(1).lower() if name_m else None

        if closing:
            if elem in _RAW_ELEMENTS:
                in_raw = False
            out.append(tag)
        elif elem in _RAW_ELEMENTS and not tag.rstrip().endswith("/>"):
            new, n = _convert_tag(tag, tc, elem)
            changed += n
            out.append(new)
            in_raw = True
        elif elem is not None:
            new, n = _convert_tag(tag, tc, elem)
            changed += n
            out.append(new)
        else:
            # 注释 / CDATA / DOCTYPE / <?xml ...?> 原样保留
            out.append(tag)
        pos = m.end()

    if pos < len(text):
        chunk = text[pos:]
        if in_raw:
            out.append(chunk)
        else:
            new, n = tc.convert(chunk)
            changed += n
            out.append(new)

    return "".join(out), changed


def update_language(text: str, lang: str) -> str:
    """更新 OPF 中的 dc:language。"""
    return _DC_LANGUAGE_RE.sub(
        lambda m: m.group(1) + lang + m.group(3), text
    )


# --------------------------------------------------------------------------- #
# 编码探测
# --------------------------------------------------------------------------- #

_cchardet = None


def _detect_encoding(data: bytes) -> str | None:
    global _cchardet
    if _cchardet is None:
        try:
            import cchardet as _cchardet_mod  # type: ignore
        except ImportError:
            try:
                import chardet as _cchardet_mod  # type: ignore
            except ImportError:
                _cchardet_mod = False  # type: ignore[assignment]
        _cchardet = _cchardet_mod
    if not _cchardet:
        return None
    try:
        result = _cchardet.detect(data)
    except Exception:  # pragma: no cover - 探测库异常不应中断转换
        return None
    enc = (result or {}).get("encoding")
    return enc or None


def decode_bytes(data: bytes) -> tuple[str, str]:
    """把文件字节解码为文本，返回 (文本, 编码名)。

    优先使用 BOM / XML 声明 / meta charset 里声明的编码，
    其次 utf-8，再次自动探测，最后 gb18030 兜底。
    """
    for bom, enc in _BOMS:
        if data.startswith(bom):
            return data.decode(enc), enc

    for rx in (_XML_DECL_RE, _META_CHARSET_RE):
        m = rx.search(data[:4096])
        if not m:
            continue
        enc = m.group(1).decode("ascii", "replace").strip()
        try:
            return data.decode(enc), enc
        except (LookupError, UnicodeDecodeError):
            continue

    try:
        return data.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        pass

    enc = _detect_encoding(data)
    if enc:
        try:
            return data.decode(enc), enc
        except (LookupError, UnicodeDecodeError):
            pass

    try:
        return data.decode("gb18030"), "gb18030"
    except UnicodeDecodeError:
        return data.decode("utf-8", "replace"), "utf-8"


# --------------------------------------------------------------------------- #
# EPUB 读写
# --------------------------------------------------------------------------- #

@dataclass
class FileResult:
    name: str
    converted: bool = False
    chars: int = 0
    encoding: str | None = None
    note: str = ""


@dataclass
class Result:
    src: Path
    config: str
    direction: str
    dst: Path | None = None
    files: list[FileResult] = field(default_factory=list)
    dry_run: bool = False
    error: str | None = None

    @property
    def changed_files(self) -> int:
        return sum(1 for f in self.files if f.converted)

    @property
    def chars(self) -> int:
        return sum(f.chars for f in self.files)

    @property
    def ok(self) -> bool:
        return self.error is None


def _should_convert(name: str, exts: frozenset[str]) -> bool:
    if name.startswith("META-INF/"):
        return False
    return os.path.splitext(name)[1].lower() in exts


def sample_text(path: Path, limit: int = 200_000) -> str:
    """抽取 EPUB 中的正文样本，用于自动判断简繁方向。"""
    chunks: list[str] = []
    total = 0
    try:
        with zipfile.ZipFile(path) as zf:
            for info in zf.infolist():
                if info.is_dir() or os.path.splitext(info.filename)[1].lower() not in _SAMPLE_EXTS:
                    continue
                data = zf.read(info.filename)
                if len(data) > 400_000:
                    data = data[:400_000]
                text, _ = decode_bytes(data)
                plain = _MARKUP_RE.sub(" ", text)
                chunks.append(plain)
                total += len(plain)
                if total >= limit:
                    break
    except (zipfile.BadZipFile, OSError) as exc:
        raise ConvertError(f"无法读取 EPUB：{exc}") from exc
    return "".join(chunks)[:limit]


def detect_direction(text: str) -> str:
    """判断文本主要为简体（返回 't'，即应转成繁体）还是繁体（返回 's'）。"""
    probe = text[:100_000]
    if not probe.strip():
        return "s"
    to_trad = get_opencc("s2t").convert(probe)
    to_simp = get_opencc("t2s").convert(probe)
    d_trad = diff_count(probe, to_trad)
    d_simp = diff_count(probe, to_simp)
    if d_trad == d_simp == 0:
        return "s"
    return "t" if d_trad >= d_simp else "s"


def convert_epub(
    src: Path,
    dst: Path,
    config: str,
    *,
    exts: frozenset[str],
    glossary: Sequence[tuple[str, str]] = (),
    entities: bool = True,
    raw: bool = False,
    update_lang: bool = False,
    variant: str = "generic",
    dry_run: bool = False,
) -> Result:
    """把 src 转换为 dst，返回统计结果。dry_run 时不写出文件。"""
    direction = config_direction(config)
    result = Result(src=src, dst=dst, config=config, direction=direction, dry_run=dry_run)
    tc = TextConverter(config, glossary, entities)
    lang = LANG_TAGS.get((direction, variant), "zh-Hant" if direction == "t" else "zh-Hans")

    tmp_path: str | None = None
    try:
        with zipfile.ZipFile(src) as zin:
            infos = zin.infolist()
            if not any(i.filename == "mimetype" for i in infos):
                result.files.append(FileResult("mimetype", note="缺少 mimetype 条目"))

            # mimetype 必须是第一个条目，其余保持原顺序
            ordered = sorted(infos, key=lambda i: (i.filename != "mimetype",))

            zout: zipfile.ZipFile | None = None
            try:
                if not dry_run:
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    fd, tmp_path = tempfile.mkstemp(dir=str(dst.parent), suffix=".tmp")
                    os.close(fd)
                    zout = zipfile.ZipFile(tmp_path, "w", zipfile.ZIP_DEFLATED)
                    zout.comment = zin.comment

                for info in ordered:
                    data = zin.read(info.filename)
                    new_data = data
                    converted = False
                    chars = 0
                    encoding: str | None = None

                    if not info.is_dir() and _should_convert(info.filename, exts):
                        text, encoding = decode_bytes(data)
                        new_text, chars = convert_document(tc, text, raw=raw)
                        if update_lang and info.filename.lower().endswith(".opf"):
                            new_text = update_language(new_text, lang)
                            chars = chars or (1 if new_text != text else 0)
                        if new_text != text:
                            new_data = new_text.encode(
                                encoding, errors="xmlcharrefreplace"
                            )
                            converted = True
                        else:
                            new_data = data
                            chars = 0

                    result.files.append(
                        FileResult(info.filename, converted, chars, encoding)
                    )
                    if zout is not None:
                        out_info = copy.copy(info)
                        if out_info.filename == "mimetype":
                            out_info.compress_type = zipfile.ZIP_STORED
                        zout.writestr(out_info, new_data)
            finally:
                if zout is not None:
                    zout.close()

        # 输入 zip 关闭后再替换输出：Windows 上原文件仍被打开时无法覆盖
        if tmp_path is not None:
            os.replace(tmp_path, dst)
            tmp_path = None
    except (zipfile.BadZipFile, RuntimeError, OSError) as exc:
        result.error = str(exc)
    finally:
        if tmp_path is not None:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
    return result


# --------------------------------------------------------------------------- #
# 术语表
# --------------------------------------------------------------------------- #

def load_glossary(paths: Sequence[str]) -> list[tuple[str, str]]:
    """加载术语表：JSON 对象，或每行 `源<TAB>目标`（也支持 `源 目标`）的文本。"""
    pairs: list[tuple[str, str]] = []
    for raw_path in paths:
        p = Path(raw_path)
        try:
            text = p.read_text(encoding="utf-8")
        except OSError as exc:
            raise ConvertError(f"无法读取术语表 {p}: {exc}") from exc
        if p.suffix.lower() == ".json":
            data = json.loads(text)
            if not isinstance(data, dict):
                raise ConvertError(f"术语表 {p} 必须是 JSON 对象")
            pairs.extend((str(k), str(v)) for k, v in data.items())
        else:
            for lineno, line in enumerate(text.splitlines(), 1):
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "\t" in line:
                    src, _, dst = line.partition("\t")
                else:
                    parts = line.split(None, 1)
                    if len(parts) != 2:
                        raise ConvertError(f"{p}:{lineno} 无法解析：{line!r}")
                    src, dst = parts
                pairs.append((src.strip(), dst.strip()))
    # 长词优先，避免短词抢先替换
    pairs.sort(key=lambda kv: -len(kv[0]))
    return pairs


# --------------------------------------------------------------------------- #
# 输出路径
# --------------------------------------------------------------------------- #

def resolve_output(
    src: Path,
    config: str,
    *,
    in_place: bool,
    out_file: Path | None,
    out_dir: Path | None,
) -> Path:
    if in_place:
        return src
    if out_file is not None:
        return out_file
    name = f"{src.stem}_{config}{src.suffix}"
    if out_dir is not None:
        return out_dir / name
    return src.with_name(name)


# --------------------------------------------------------------------------- #
# 终端输出（Windows / Linux / macOS）
# --------------------------------------------------------------------------- #

_COLORS = {
    "reset": "\033[0m",
    "bold": "\033[1m",
    "dim": "\033[2m",
    "red": "\033[31m",
    "green": "\033[32m",
    "yellow": "\033[33m",
    "cyan": "\033[36m",
}


def configure_stdio() -> None:
    """尽量让标准流按 UTF-8 工作，避免 Windows 控制台编码报错。

    Windows 默认使用本地代码页（cp936 / cp1252…），直接输出中文或 ``✓``
    这类符号可能抛 ``UnicodeEncodeError``。这里在可能时把标准流切到 UTF-8
    并把无法编码的字符替换掉；Linux / macOS 本来就是 UTF-8，不受影响。

    若用户显式设置了 ``PYTHONIOENCODING``，则尊重其选择，不做改动。
    """
    if os.environ.get("PYTHONIOENCODING"):
        return
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        enc = (getattr(stream, "encoding", None) or "").replace("-", "").lower()
        if enc in ("utf8", "utf8sig", "cp65001"):
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError, LookupError):
            pass


def _stream_supports(stream, text: str) -> bool:
    """判断某个流能否原样编码给定文本（用于装饰符号降级）。"""
    enc = getattr(stream, "encoding", None) or "utf-8"
    try:
        text.encode(enc)
    except (LookupError, UnicodeEncodeError):
        return False
    return True


def _terminal_width(default: int = 80) -> int:
    try:
        return shutil.get_terminal_size((default, 24)).columns
    except OSError:  # pragma: no cover - 某些特殊终端会报错
        return default


class Console:
    """统一的终端输出：颜色开关 + 符号降级，跨平台安全。

    颜色默认只在真正的 TTY 上开启，并遵循 ``NO_COLOR`` 环境变量；
    不能编码 Unicode 的终端会自动把 ``✓`` / ``✗`` / ``·`` 降级为 ASCII。
    """

    def __init__(self, color: str = "auto", stdout=None, stderr=None) -> None:
        self.stdout = stdout if stdout is not None else sys.stdout
        self.stderr = stderr if stderr is not None else sys.stderr
        self._color = self._decide_color(color)
        self.unicode = _stream_supports(self.stdout, "✓")
        self.ok_mark = "✓" if self.unicode else "OK"
        self.fail_mark = "✗" if self.unicode else "ERR"
        self.bullet = "·" if self.unicode else "-"

    def _decide_color(self, mode: str) -> bool:
        if mode == "always":
            return True
        if mode == "never" or os.environ.get("NO_COLOR"):
            return False
        if os.environ.get("TERM", "") == "dumb":
            return False
        isatty = getattr(self.stdout, "isatty", None)
        return bool(isatty and isatty())

    def paint(self, text: str, *styles: str) -> str:
        if not self._color or not styles:
            return text
        prefix = "".join(_COLORS.get(s, "") for s in styles)
        return f"{prefix}{text}{_COLORS['reset']}"

    def out(self, text: str = "") -> None:
        print(text, file=self.stdout)

    def err(self, text: str = "") -> None:
        print(text, file=self.stderr)


class Progress:
    """批量处理时的单行进度提示（只在真正的终端上启用）。"""

    def __init__(self, total: int, stream, enabled: bool) -> None:
        self.total = total
        self.stream = stream
        self.enabled = bool(enabled) and total > 1
        self.done = 0
        self._width = len(str(total))

    def advance(self, name: str) -> None:
        if not self.enabled:
            return
        self.done += 1
        columns = _terminal_width()
        text = f"[{self.done:>{self._width}}/{self.total}] {name}"
        if len(text) > columns - 1:
            text = text[: max(0, columns - 2)] + "~"
        self.stream.write("\r" + text.ljust(columns - 1))
        self.stream.flush()

    def finish(self) -> None:
        if not self.enabled:
            return
        self.stream.write("\r" + " " * (_terminal_width() - 1) + "\r")
        self.stream.flush()


# --------------------------------------------------------------------------- #
# 主流程
# --------------------------------------------------------------------------- #

def collect_inputs(inputs: Iterable[str], recursive: bool) -> tuple[list[Path], list[str]]:
    files: list[Path] = []
    problems: list[str] = []
    seen: set[Path] = set()
    for raw in inputs:
        p = Path(raw)
        if p.is_dir():
            pattern = "**/*" if recursive else "*"
            found = [
                q for q in sorted(p.glob(pattern))
                if q.is_file() and q.suffix.lower() == ".epub"
            ]
            if not found:
                problems.append(f"目录中没有找到 EPUB：{p}")
            for q in found:
                if q not in seen:
                    seen.add(q)
                    files.append(q)
        elif p.is_file():
            if p not in seen:
                seen.add(p)
                files.append(p)
        else:
            problems.append(f"路径不存在：{p}")
    return files, problems


def process_one(
    src: Path,
    args: argparse.Namespace,
    exts: frozenset[str],
    glossary: Sequence[tuple[str, str]],
    out_file: Path | None,
    out_dir: Path | None,
) -> Result:
    try:
        if args.direction != "auto":
            config = args.direction
        elif args.target is not None:
            config = VARIANTS[(args.target, args.variant)]
        else:
            config = VARIANTS[(detect_direction(sample_text(src)), args.variant)]
    except ConvertError as exc:
        return Result(src=src, config=args.direction, direction="?", error=str(exc))
    except (zipfile.BadZipFile, OSError) as exc:
        return Result(src=src, config=args.direction, direction="?", error=str(exc))

    direction = config_direction(config)
    variant = args.variant
    if variant == "generic":
        variant = infer_variant(config)
    dst = resolve_output(
        src, config, in_place=args.in_place, out_file=out_file, out_dir=out_dir
    )

    if dst != src and dst.exists() and not args.force:
        return Result(
            src=src, dst=dst, config=config, direction=direction,
            error=f"输出文件已存在（使用 -f/--force 覆盖）：{dst}",
        )

    if args.in_place and not args.no_backup and not args.dry_run:
        backup = src.with_name(src.name + ".bak")
        try:
            if not backup.exists() or args.force:
                shutil.copy2(src, backup)
        except OSError as exc:
            return Result(
                src=src, dst=dst, config=config, direction=direction,
                error=f"无法创建备份 {backup}：{exc}",
            )

    return convert_epub(
        src, dst, config,
        exts=exts, glossary=glossary, entities=args.entities, raw=args.raw,
        update_lang=args.update_language, variant=variant, dry_run=args.dry_run,
    )


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog=PROG,
        description="EPUB 电子书简繁中文转换工具（基于 OpenCC）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例:\n"
            "  epubcc book.epub                    # 自动判断方向\n"
            "  epubcc -t book.epub                 # 简体 -> 繁体\n"
            "  epubcc -s --variant tw book.epub    # 台湾正体 -> 简体\n"
            "  epubcc -d s2twp -o out/ book.epub   # 指定 OpenCC 配置与输出目录\n"
            "  epubcc -t -i book.epub              # 原地转换并生成 .bak 备份\n"
            "  epubcc -t -r books/                 # 递归批量转换\n\n"
            "方向由目标决定：-t 输出繁体、-s 输出简体；\n"
            "不加时自动探测原文，简体转繁、繁体转简。"
        ),
    )
    p.add_argument("inputs", nargs="*", help="EPUB 文件，或包含 EPUB 的目录")

    g = p.add_mutually_exclusive_group()
    g.add_argument("-t", "--to-traditional", dest="target", action="store_const",
                   const="t", help="输出繁体（简体 -> 繁体）")
    g.add_argument("-s", "--to-simplified", dest="target", action="store_const",
                   const="s", help="输出简体（繁体 -> 简体）")

    p.add_argument("-d", "--direction", default="auto",
                   choices=["auto", *OPENCC_CONFIGS],
                   help="直接指定 OpenCC 配置（默认 auto：自动判断）")
    p.add_argument("--variant", default="generic",
                   choices=["generic", "tw", "twp", "hk"],
                   help="用词变体：generic=通用，tw=台湾，twp=台湾+词汇，"
                        "hk=香港（默认 generic）")

    p.add_argument("-o", "--output", metavar="PATH",
                   help="输出文件或目录；以 .epub 结尾视为文件，否则视为目录")
    p.add_argument("-i", "--in-place", action="store_true",
                   help="原地转换（默认生成 .bak 备份）")
    p.add_argument("--no-backup", action="store_true",
                   help="原地转换时不生成 .bak 备份")
    p.add_argument("-f", "--force", action="store_true",
                   help="覆盖已存在的输出文件 / 备份文件")
    p.add_argument("-r", "--recursive", action="store_true",
                   help="递归查找目录中的 EPUB")

    p.add_argument("--ext", action="append", default=[], metavar="EXT",
                   help="额外参与转换的扩展名（可重复，如 --ext .css）")
    p.add_argument("--include-css", action="store_true",
                   help="同时转换 .css（默认不转换，避免影响字体名等）")
    p.add_argument("--raw", action="store_true",
                   help="不做标签感知，直接转换整份文本（慎用）")
    p.add_argument("--no-numeric-entities", dest="entities", action="store_false",
                   help="不转换 &#x4E2D; 这类数字字符引用")
    p.add_argument("--glossary", action="append", default=[], metavar="FILE",
                   help="自定义术语表（JSON 或 TSV，可重复）")
    p.add_argument("--update-language", action="store_true",
                   help="同时更新 OPF 中的 dc:language")

    p.add_argument("-j", "--jobs", type=int, default=0,
                   help="并行处理的文件数（默认按 CPU 数，1 表示串行）")
    p.add_argument("-n", "--dry-run", action="store_true",
                   help="只统计不写出文件")
    p.add_argument("-q", "--quiet", action="store_true", help="只输出错误")
    p.add_argument("-v", "--verbose", action="store_true", help="输出每个文件的详情")
    p.add_argument("--color", choices=["auto", "always", "never"], default="auto",
                   help="彩色输出：auto=仅 TTY（默认）、always、never，"
                        "也遵循 NO_COLOR 环境变量")
    p.add_argument("--no-progress", action="store_true",
                   help="关闭批量处理的进度提示（TTY 上默认开启）")
    p.add_argument("-V", "--version", action="version",
                   version=f"{PROG} {__version__}")
    p.add_argument("--list-configs", action="store_true",
                   help="列出可用的 OpenCC 配置后退出")
    return p


def _exts_from_args(args: argparse.Namespace) -> frozenset[str]:
    exts = set(DEFAULT_TEXT_EXTS)
    if args.include_css:
        exts.add(".css")
    for item in args.ext:
        for part in item.replace(" ", ",").split(","):
            part = part.strip()
            if not part:
                continue
            exts.add(part if part.startswith(".") else "." + part)
    return frozenset(e.lower() for e in exts)


def main(argv: Sequence[str] | None = None) -> int:
    configure_stdio()
    parser = build_parser()

    if argcomplete is not None:  # pragma: no cover - 仅在交互式补全时生效
        argcomplete.autocomplete(parser)

    args = parser.parse_args(argv)
    console = Console(getattr(args, "color", "auto"))

    if args.list_configs:
        console.out("可用 OpenCC 配置：")
        for c in OPENCC_CONFIGS:
            console.out(f"  {c}")
        return 0

    if args.jobs < 0:
        parser.error("--jobs 不能为负数")

    if not args.inputs:
        parser.error("至少需要指定一个 EPUB 文件或目录")

    try:
        glossary = load_glossary(args.glossary)
    except ConvertError as exc:
        console.err(console.paint(f"错误：{exc}", "red"))
        return 2

    files, problems = collect_inputs(args.inputs, args.recursive)
    for msg in problems:
        console.err(console.paint(f"警告：{msg}", "yellow"))
    if not files:
        console.err(console.paint("错误：没有可处理的 EPUB 文件", "red"))
        return 1

    exts = _exts_from_args(args)
    multi = len(files) > 1
    out_file: Path | None = None
    out_dir: Path | None = None
    if args.output:
        raw_out = args.output
        out_path = Path(raw_out)
        is_file_like = (
            not raw_out.endswith((os.sep, "/"))
            and not out_path.is_dir()
            and out_path.suffix.lower() == ".epub"
        )
        if multi and is_file_like:
            parser.error("有多个输入时 --output 必须是目录")
        # 以路径分隔符结尾、已存在的目录、包含多个输入，或没有 .epub 后缀时
        # 视为输出目录；否则视为输出文件。
        if multi or out_path.is_dir() or not is_file_like:
            out_dir = out_path
        else:
            out_file = out_path

    jobs = args.jobs or min(8, os.cpu_count() or 1)
    jobs = max(1, min(jobs, len(files)))

    results: list[Result] = []
    stderr_tty = bool(getattr(console.stderr, "isatty", lambda: False)())
    progress = Progress(
        len(files), console.stderr,
        enabled=not args.quiet and not args.no_progress and stderr_tty,
    )
    if jobs == 1:
        for f in files:
            results.append(process_one(f, args, exts, glossary, out_file, out_dir))
            progress.advance(f.name)
    else:
        with concurrent.futures.ThreadPoolExecutor(max_workers=jobs) as pool:
            future_map = {
                pool.submit(process_one, f, args, exts, glossary, out_file, out_dir): f
                for f in files
            }
            for fut in concurrent.futures.as_completed(future_map):
                results.append(fut.result())
                progress.advance(future_map[fut].name)
    progress.finish()

    order = {f: i for i, f in enumerate(files)}
    results.sort(key=lambda r: order.get(r.src, 0))

    failures = 0
    total_chars = 0
    total_changed = 0
    for r in results:
        if not r.ok:
            failures += 1
            console.err(console.paint(f"{console.fail_mark} {r.src}：{r.error}", "red"))
            continue
        total_chars += r.chars
        total_changed += r.changed_files
        if args.quiet:
            continue
        action = "统计" if r.dry_run else "写出"
        arrow = f" -> {r.dst}" if r.dst and r.dst != r.src else "（原地）"
        hint = "" if r.changed_files else "   （无变化，可能已是目标字形）"
        mark = console.paint(console.ok_mark, "green")
        console.out(
            f"{mark} {r.src.name}{arrow}  [{r.config}]  "
            f"{action} {r.changed_files} 个文件 / {r.chars} 字{hint}"
        )
        if args.verbose:
            for fr in r.files:
                if fr.converted:
                    enc = f" ({fr.encoding})" if fr.encoding else ""
                    console.out(f"    {console.bullet} {fr.name}{enc}  {fr.chars} 字")

    if not args.quiet and len(results) > 1:
        console.out(console.paint(
            f"合计：{len(results) - failures}/{len(results)} 本成功，"
            f"{total_changed} 个文件 / {total_chars} 字被转换"
            + ("（dry-run，未写出）" if args.dry_run else ""),
            "bold",
        ))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
