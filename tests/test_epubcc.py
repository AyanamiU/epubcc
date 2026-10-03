#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""epubcc 的单元测试：python3 -m unittest discover -s tests -v"""

from __future__ import annotations

import contextlib
import io
import os
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import epubcc  # noqa: E402

CONTAINER = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<container version="1.0" '
    'xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
    '<rootfiles><rootfile full-path="OEBPS/content.opf" '
    'media-type="application/oebps-package+xml"/></rootfiles></container>'
)

OPF_TMPL = (
    '<?xml version="1.0" encoding="utf-8"?>'
    '<package xmlns="http://www.idpf.org/2007/opf" version="2.0" '
    'unique-identifier="id"><metadata '
    'xmlns:dc="http://purl.org/dc/elements/1.1/">'
    "<dc:title>{title}</dc:title><dc:language>{lang}</dc:language>"
    "<dc:description>{desc}</dc:description></metadata>"
    '<manifest><item id="c1" href="chapter1.xhtml" '
    'media-type="application/xhtml+xml"/>'
    '<item id="css" href="style.css" media-type="text/css"/></manifest>'
    "<spine><itemref idref=\"c1\"/></spine></package>"
)

XHTML_TMPL = (
    '<?xml version="1.0" encoding="{enc}"?>'
    "<!DOCTYPE html>"
    '<html xmlns="http://www.w3.org/1999/xhtml"><head>'
    '<meta charset="{enc}"/><title>{title}</title>'
    '<script>var s = "软件";</script><style>p {{ content: "数据"; }}</style>'
    "</head><body>"
    '<h1 title="{tip}">{h1}</h1>'
    "<p>{body}</p>"
    '<img src="images/中文图片.png" alt="{alt}"/>'
    "<!-- 注释里的软件不应被转换 -->"
    "</body></html>"
)

CSS_TEXT = 'body { font-family: "宋体", serif; } p:after { content: "资料"; }'

BINARY = b"\x89PNG\r\n\x1a\n\x00\x00\xe8\xbd\xaf\xe4\xbb\xb6"  # 含 UTF-8 汉字



def make_epub(
    path: Path,
    *,
    title: str = "测试书：软件与信息",
    desc: str = "这是一本关于网络与数据的书。",
    lang: str = "zh-CN",
    h1: str = "第一章 计算机",
    body: str = "这是一个<em>测试</em>，含软件与实体&#x8F6F;&#20214;。",
    tip: str = "后台管理",
    alt: str = "封面图",
    encoding: str = "utf-8",
    comment: bytes = b"epubcc-test",
) -> Path:
    opf = OPF_TMPL.format(title=title, desc=desc, lang=lang)
    xhtml = XHTML_TMPL.format(
        enc=encoding, title=h1, tip=tip, h1=h1, body=body, alt=alt
    )
    with zipfile.ZipFile(path, "w") as z:
        z.writestr(
            zipfile.ZipInfo("mimetype"),
            "application/epub+zip",
            compress_type=zipfile.ZIP_STORED,
        )
        z.writestr("META-INF/container.xml", CONTAINER)
        z.writestr("OEBPS/content.opf", opf.encode(encoding))
        z.writestr("OEBPS/chapter1.xhtml", xhtml.encode(encoding))
        z.writestr("OEBPS/style.css", CSS_TEXT.encode(encoding))
        z.writestr("OEBPS/images/cover.png", BINARY)
        z.comment = comment
    return path


def read(path: Path, name: str, encoding: str = "utf-8") -> str:
    with zipfile.ZipFile(path) as z:
        return z.read(name).decode(encoding)


class EpubccTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.src = make_epub(self.dir / "book.epub")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def run_cli(self, *argv: str) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = epubcc.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    # ------------------------------------------------------------------ #

    def test_s2t_basic(self) -> None:
        code, _, _ = self.run_cli("-t", str(self.src))
        self.assertEqual(code, 0)
        dst = self.dir / "book_s2t.epub"
        self.assertTrue(dst.exists())

        html = read(dst, "OEBPS/chapter1.xhtml")
        # 正文、标题、属性、数字实体都转换
        self.assertIn("第一章 計算機", html)
        self.assertIn("這是一個<em>測試</em>", html)
        self.assertIn('title="後臺管理"', html)
        self.assertIn('alt="封面圖"', html)
        self.assertIn("&#x8EDF;&#20214;", html)
        # script / style / 注释保持原样
        self.assertIn('var s = "软件";', html)
        self.assertIn('content: "数据";', html)
        self.assertIn("注释里的软件不应被转换", html)
        # URL 属性中的中文文件名不被破坏
        self.assertIn('src="images/中文图片.png"', html)
        # OPF 元数据
        opf = read(dst, "OEBPS/content.opf")
        self.assertIn("測試書：軟件與信息", opf)
        self.assertIn("網絡與數據", opf)

    def test_zip_structure_preserved(self) -> None:
        self.run_cli("-t", str(self.src))
        dst = self.dir / "book_s2t.epub"
        with zipfile.ZipFile(dst) as z:
            names = z.namelist()
            self.assertEqual(names[0], "mimetype")
            self.assertEqual(z.getinfo("mimetype").compress_type, zipfile.ZIP_STORED)
            self.assertEqual(z.comment, b"epubcc-test")
            self.assertEqual(z.read("OEBPS/images/cover.png"), BINARY)
            self.assertEqual(z.read("OEBPS/style.css"), CSS_TEXT.encode())
            self.assertEqual(set(names), set(zipfile.ZipFile(self.src).namelist()))

    def test_t2s_auto_detect(self) -> None:
        trad = self.dir / "trad.epub"
        make_epub(
            trad,
            title="繁體書：軟體與資訊",
            desc="這是一本關於網路與資料的書。",
            h1="第一章 電腦",
            body="這是一個測試。",
            tip="後臺管理",
            alt="封面圖",
            lang="zh-TW",
        )
        code, out, _ = self.run_cli(str(trad))
        self.assertEqual(code, 0)
        dst = self.dir / "trad_t2s.epub"
        self.assertIn("t2s", out)
        self.assertIn("第一章 电脑", read(dst, "OEBPS/chapter1.xhtml"))
        self.assertIn("这是一本关于网路与资料的书。", read(dst, "OEBPS/content.opf"))

    def test_auto_detect_simplified(self) -> None:
        _, out, _ = self.run_cli(str(self.src))
        self.assertIn("[s2t]", out)
        self.assertTrue((self.dir / "book_s2t.epub").exists())

    def test_traditional_variant(self) -> None:
        code, _, _ = self.run_cli("-t", "--variant", "twp", str(self.src))
        self.assertEqual(code, 0)
        html = read(self.dir / "book_s2twp.epub", "OEBPS/chapter1.xhtml")
        self.assertIn("第一章 計算機", html)

    def test_gbk_encoding_preserved(self) -> None:
        gbk = self.dir / "gbk.epub"
        make_epub(gbk, title="测试书", h1="第一章", body="这是一个测试。", encoding="gbk")
        code, _, _ = self.run_cli("-t", str(gbk))
        self.assertEqual(code, 0)
        data = None
        with zipfile.ZipFile(self.dir / "gbk_s2t.epub") as z:
            data = z.read("OEBPS/chapter1.xhtml")
        text = data.decode("gbk")  # 仍可用 GBK 解码
        self.assertIn("第一章", text)

    def test_glossary(self) -> None:
        gloss = self.dir / "g.txt"
        gloss.write_text("软件\t软体\n# comment\n测试 测验\n", encoding="utf-8")
        code, _, _ = self.run_cli("-t", "--glossary", str(gloss), str(self.src))
        self.assertEqual(code, 0)
        html = read(self.dir / "book_s2t.epub", "OEBPS/chapter1.xhtml")
        self.assertIn("軟體", html)
        self.assertIn("測驗", html)  # 整词优先于 s2t 的「測試」

    def test_glossary_json(self) -> None:
        gloss = self.dir / "g.json"
        gloss.write_text('{"软件": "軟體"}', encoding="utf-8")
        self.run_cli("-t", "--glossary", str(gloss), str(self.src))
        self.assertIn("軟體", read(self.dir / "book_s2t.epub", "OEBPS/chapter1.xhtml"))
    def test_include_css(self) -> None:
        self.run_cli("-t", "--include-css", str(self.src))
        css = read(self.dir / "book_s2t.epub", "OEBPS/style.css")
        self.assertIn("資料", css)
        self.assertIn("宋體", css)
        # 默认不动 CSS
        self.run_cli("-t", "-f", str(self.src))
        self.assertEqual(
            read(self.dir / "book_s2t.epub", "OEBPS/style.css"), CSS_TEXT
        )

    def test_raw_mode(self) -> None:
        self.run_cli("-t", "--raw", str(self.src))
        html = read(self.dir / "book_s2t.epub", "OEBPS/chapter1.xhtml")
        self.assertIn('var s = "軟件";', html)  # raw 模式连 script 也转换
        self.assertIn("註釋裏的軟件", html)

    def test_no_numeric_entities(self) -> None:
        self.run_cli("-t", "--no-numeric-entities", str(self.src))
        html = read(self.dir / "book_s2t.epub", "OEBPS/chapter1.xhtml")
        self.assertIn("&#x8F6F;&#20214;", html)

    def test_update_language(self) -> None:
        self.run_cli("-t", "--update-language", str(self.src))
        self.assertIn("<dc:language>zh-Hant</dc:language>",
                      read(self.dir / "book_s2t.epub", "OEBPS/content.opf"))
        self.run_cli("-t", "--variant", "tw", "--update-language", str(self.src))
        self.assertIn("<dc:language>zh-TW</dc:language>",
                      read(self.dir / "book_s2tw.epub", "OEBPS/content.opf"))

    def test_in_place_with_backup(self) -> None:
        before = self.src.read_bytes()
        code, _, _ = self.run_cli("-t", "-i", str(self.src))
        self.assertEqual(code, 0)
        self.assertEqual((self.dir / "book.epub.bak").read_bytes(), before)
        self.assertIn("計算機", read(self.src, "OEBPS/chapter1.xhtml"))
        # 不修改源文件
        self.assertNotEqual(self.src.read_bytes(), before)
        # 结构仍完好
        with zipfile.ZipFile(self.src) as z:
            self.assertEqual(z.namelist()[0], "mimetype")

    def test_in_place_no_backup(self) -> None:
        self.run_cli("-t", "-i", "--no-backup", str(self.src))
        self.assertFalse((self.dir / "book.epub.bak").exists())

    def test_dry_run(self) -> None:
        code, out, _ = self.run_cli("-t", "--dry-run", str(self.src))
        self.assertEqual(code, 0)
        self.assertFalse((self.dir / "book_s2t.epub").exists())
        self.assertIn("统计", out)

    def test_force_required(self) -> None:
        (self.dir / "book_s2t.epub").write_bytes(b"existing")
        code, _, err = self.run_cli("-t", str(self.src))
        self.assertEqual(code, 1)
        self.assertIn("已存在", err)
        self.assertEqual((self.dir / "book_s2t.epub").read_bytes(), b"existing")
        code, _, _ = self.run_cli("-t", "-f", str(self.src))
        self.assertEqual(code, 0)

    def test_directory_recursive(self) -> None:
        sub = self.dir / "sub"
        sub.mkdir()
        make_epub(sub / "a.epub", title="甲书", h1="甲", body="甲书内容。")
        out = self.dir / "out"
        code, _, _ = self.run_cli("-t", "-r", "-o", str(out), str(self.dir))
        self.assertEqual(code, 0)
        self.assertTrue((out / "book_s2t.epub").exists())
        self.assertTrue((out / "a_s2t.epub").exists())
        self.assertIn("甲書內容", read(out / "a_s2t.epub", "OEBPS/chapter1.xhtml"))

    def test_output_file(self) -> None:
        code, _, _ = self.run_cli("-t", "-o", str(self.dir / "custom.epub"), str(self.src))
        self.assertEqual(code, 0)
        self.assertTrue((self.dir / "custom.epub").exists())

    def test_bad_zip(self) -> None:
        bad = self.dir / "bad.epub"
        bad.write_bytes(b"not a zip at all")
        code, _, err = self.run_cli("-t", str(bad))
        self.assertEqual(code, 1)
        self.assertIn("bad.epub", err)

    def test_missing_path(self) -> None:
        code, _, err = self.run_cli("-t", str(self.dir / "nope.epub"))
        self.assertEqual(code, 1)
        self.assertIn("没有可处理", err)

    def test_parallel_matches_serial(self) -> None:
        make_epub(self.dir / "b.epub", title="乙书", h1="乙", body="乙书内容。")
        code, _, _ = self.run_cli("-t", "-j", "2", "-o", str(self.dir / "p"), str(self.dir))
        self.assertEqual(code, 0)
        self.assertIn("乙書內容", read(self.dir / "p/b_s2t.epub", "OEBPS/chapter1.xhtml"))
        self.assertIn("第一章 計算機", read(self.dir / "p/book_s2t.epub", "OEBPS/chapter1.xhtml"))

    def test_html5_charset_meta(self) -> None:
        data = b'<meta charset="utf-8"><p>'
        self.assertEqual(epubcc.decode_bytes(data)[1], "utf-8")
        data2 = '<meta charset="gbk"><p>软件</p>'.encode("gbk")
        self.assertEqual(epubcc.decode_bytes(data2)[1], "gbk")

    # ---------------------- CLI 体验 / 跨平台 ---------------------- #

    def test_list_configs(self) -> None:
        code, out, _ = self.run_cli("--list-configs")
        self.assertEqual(code, 0)
        self.assertIn("s2twp", out)

    def test_color_always(self) -> None:
        code, out, _ = self.run_cli("-t", "-n", "--color", "always", str(self.src))
        self.assertEqual(code, 0)
        self.assertIn("\033[", out)

    def test_color_never(self) -> None:
        code, out, _ = self.run_cli("-t", "-n", "--color", "never", str(self.src))
        self.assertEqual(code, 0)
        self.assertNotIn("\033[", out)

    def test_no_progress_flag(self) -> None:
        code, _, _ = self.run_cli("-t", "-n", "--no-progress", str(self.src))
        self.assertEqual(code, 0)

    def test_console_ascii_fallback(self) -> None:
        class Ascii(io.StringIO):
            encoding = "ascii"

        console = epubcc.Console("never", stdout=Ascii(), stderr=Ascii())
        self.assertFalse(console.unicode)
        self.assertEqual(console.ok_mark, "OK")
        self.assertEqual(console.fail_mark, "ERR")
        self.assertEqual(console.bullet, "-")

    def test_console_unicode_default(self) -> None:
        console = epubcc.Console("never", stdout=io.StringIO(), stderr=io.StringIO())
        self.assertTrue(console.unicode)
        self.assertEqual(console.ok_mark, "✓")

    def test_console_no_color_env(self) -> None:
        class Tty(io.StringIO):
            def isatty(self) -> bool:
                return True

        old = os.environ.get("NO_COLOR")
        try:
            os.environ["NO_COLOR"] = "1"
            console = epubcc.Console("auto", stdout=Tty(), stderr=Tty())
            self.assertEqual(console.paint("x", "red"), "x")
            os.environ.pop("NO_COLOR", None)
            console = epubcc.Console("auto", stdout=Tty(), stderr=Tty())
            self.assertIn("\033[", console.paint("x", "red"))
        finally:
            if old is None:
                os.environ.pop("NO_COLOR", None)
            else:
                os.environ["NO_COLOR"] = old

    def test_configure_stdio_is_safe(self) -> None:
        # 在 StringIO 上（无 reconfigure）不应报错
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            epubcc.configure_stdio()

    def test_no_temp_files_left(self) -> None:
        self.run_cli("-t", "-i", str(self.src))
        leftovers = [p.name for p in self.dir.iterdir() if p.name.endswith(".tmp")]
        self.assertEqual(leftovers, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
