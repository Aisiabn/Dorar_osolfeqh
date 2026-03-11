#!/usr/bin/env python3
"""
dorar_osolfeqh_export.py — Export dorar.net/osolfeqh to EPUB + Markdown
Usage:
    python scraper.py
    TEST_PAGES=10 python scraper.py
"""

import os
import re
import time
import uuid
import zipfile
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup, NavigableString, Tag

# ── Config ────────────────────────────────────────────────────────────────────
START_URL   = "https://dorar.net/osolfeqh"
PAGE_RE     = re.compile(r"/osolfeqh/(\d+)")
SKIP_CRUMBS = 2          # "الرئيسة" + "موسوعة أصول الفقه"
DELAY       = 0.5
TIMEOUT     = 20
TEST_PAGES  = int(os.getenv("TEST_PAGES") or 0)
OUT_DIR     = Path("output")
EPUB_PATH   = OUT_DIR / "osolfeqh.epub"
MD_DIR      = OUT_DIR / "md"
BOOK_TITLE  = "موسوعة أصول الفقه"

FRONT_PAGES: list[tuple[str, str]] = []   # أضف روابط مقدمة إن وجدت
BACK_PAGES:  list[tuple[str, str]] = [
    ("المراجع المعتمدة", "https://dorar.net/refs/osolfeqh"),
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 6.1; WOW64) AppleWebKit/537.36 "
        "Chrome/109.0.0.0"
    ),
    "Accept-Language": "ar,en-US;q=0.9,en;q=0.8",
}

CHILDREN_NAMES = {
    1: "باب", 2: "فصل", 3: "مبحث", 4: "مطلب", 5: "فرع", 6: "مسألة"
}

PUA_RE      = re.compile(r"[\ue000-\uf8ff]")
SAFE_RE     = re.compile(r'[\\/:*?"<>|]')
NAV_TEXT_RE = re.compile(
    r"السابق|التالي|انظر\s+أيض|الرابط\s+المختصر|مشاركة|share",
    re.I,
)

# ── HTTP Session ──────────────────────────────────────────────────────────────
_session = requests.Session()
_session.headers.update(HEADERS)


def fetch(url: str) -> BeautifulSoup | None:
    try:
        r = _session.get(url, timeout=TIMEOUT)
        r.raise_for_status()
        r.encoding = "utf-8"
        return BeautifulSoup(r.text, "html.parser")
    except Exception as exc:
        print(f"  [ERROR] {url}: {exc}")
        return None


# ── Data Classes ──────────────────────────────────────────────────────────────
@dataclass
class Page:
    pid:        str
    url:        str
    title:      str
    level:      int
    breadcrumb: list[str]
    body_html:  str
    footnotes:  list[tuple[str, str]]

    def epub_filename(self) -> str:
        return f"p{self.pid}.xhtml"


@dataclass
class IndexPage:
    pid:      str
    title:    str
    level:    int
    children: list[str]

    def epub_filename(self) -> str:
        return f"p{self.pid}.xhtml"


Item = Page | IndexPage


# ── Helpers ───────────────────────────────────────────────────────────────────
def _count_phrase(n: int, child_type: str) -> str:
    if n == 1:
        return f"وفيه {child_type} واحد"
    elif n == 2:
        return f"وفيه {child_type}ان"
    elif 3 <= n <= 10:
        plurals = {
            "باب": "أبواب", "فصل": "فصول", "مبحث": "مباحث",
            "مطلب": "مطالب", "فرع": "فروع", "مسألة": "مسائل",
        }
        return f"وفيه {n} {plurals.get(child_type, child_type + 'ات')}"
    else:
        plurals = {
            "باب": "باباً", "فصل": "فصلاً", "مبحث": "مبحثاً",
            "مطلب": "مطلباً", "فرع": "فرعاً", "مسألة": "مسألةً",
        }
        return f"وفيه {n} {plurals.get(child_type, child_type)}"


def safe_name(s: str, maxlen: int = 80) -> str:
    s = SAFE_RE.sub("", s).replace(" ", "_")
    return s[:maxlen]


_folder_counters: dict[tuple, int] = {}
_folder_names:    dict[tuple, str] = {}


def numbered_folder(ancestors: list[str], depth: int) -> str:
    key = tuple(ancestors[:depth + 1])
    if key in _folder_names:
        return _folder_names[key]
    parent_key = tuple(ancestors[:depth])
    _folder_counters[parent_key] = _folder_counters.get(parent_key, 0) + 1
    n    = _folder_counters[parent_key]
    name = f"{n:02d}_{safe_name(ancestors[depth])}"
    _folder_names[key] = name
    return name


# ── Extra Pages ───────────────────────────────────────────────────────────────
def fetch_extra_page(title: str, url: str, pid: str, level: int = 1) -> Page | None:
    soup = fetch(url)
    if not soup:
        return None
    time.sleep(DELAY)

    body = (
        soup.find("div", id="cntnt")
        or soup.find("div", class_=lambda c: c and "amiri_custom_content" in c)
        or soup.find("article")
        or soup.find("main")
    )
    if not body:
        divs = soup.find_all("div")
        body = max(divs, key=lambda d: len(d.get_text()), default=None)

    body_html = BeautifulSoup(str(body), "html.parser").decode_contents() if body else ""
    cleaned   = BeautifulSoup(body_html, "html.parser")
    for el in cleaned.find_all("a"):
        if NAV_TEXT_RE.search(el.get_text()):
            el.decompose()
    body_html = cleaned.decode_contents()

    return Page(
        pid=pid, url=url, title=title, level=level,
        breadcrumb=[title], body_html=body_html, footnotes=[],
    )


# ── Discovery ─────────────────────────────────────────────────────────────────
def discover_urls() -> list[str]:
    print(f"  جلب فهرس الروابط من {START_URL}…")
    soup = fetch(START_URL)
    if not soup:
        return []

    mtree = soup.find("ul", id="mtree")
    if not mtree:
        mtree = soup.find("ul", class_="dorar_accordion_treeview")
    if not mtree:
        print("  [خطأ] لم يُعثر على قائمة الفهرس")
        return []

    seen, urls = set(), []
    for a in mtree.find_all("a", href=PAGE_RE):
        href = a["href"]
        if href not in seen:
            seen.add(href)
            urls.append(urljoin("https://dorar.net", href))

    print(f"  {len(urls)} رابط مرتب حسب الفهرس")

    if TEST_PAGES:
        urls = urls[:TEST_PAGES]
        print(f"  [وضع الاختبار] أول {TEST_PAGES} روابط فقط")

    return urls


# ── Parsing ───────────────────────────────────────────────────────────────────
def page_title(soup: BeautifulSoup) -> str:
    og = soup.find("meta", property="og:title")
    if og and og.get("content"):
        return og["content"].split(" - ")[0].strip()
    t = soup.find("title")
    return t.get_text().split(" - ")[0].strip() if t else "بدون عنوان"


def page_breadcrumb(soup: BeautifulSoup) -> list[str]:
    bc_el = soup.find("ol", class_="breadcrumb")
    if not bc_el:
        return []
    return [
        li.get_text(strip=True)
        for li in bc_el.find_all("li")
        if li.get_text(strip=True)
    ]


def extract_content(soup: BeautifulSoup, pid: str) -> tuple[str, list[tuple[str, str]]]:
    cntnt = soup.find("div", id="cntnt")
    if not cntnt:
        cntnt = soup.find("div", class_=lambda c: c and "amiri_custom_content" in c)
    if not cntnt:
        return "", []

    body = BeautifulSoup(str(cntnt), "html.parser")

    for a in body.find_all("a", href=True):
        if "/hadith/sharh/" in a["href"] or "/tafseer/" in a["href"]:
            a.decompose()

    for h3 in body.find_all("h3", id="more-titles"):
        nxt = h3.find_next_sibling("ul")
        if nxt:
            nxt.decompose()
        h3.decompose()

    for el in body.find_all("span", class_="scroll-pos"):
        el.decompose()

    for hr in body.find_all("hr"):
        nxt = hr.find_next_sibling()
        if nxt:
            nxt.decompose()
        hr.decompose()

    for a in body.find_all("a"):
        if NAV_TEXT_RE.search(a.get_text()):
            a.decompose()

    footnotes: list[tuple[str, str]] = []
    fn_n = 0
    for span in body.find_all("span", class_="tip"):
        fn_text = span.get_text(strip=True)
        fn_n += 1
        fn_id = f"fn-{pid}-{fn_n}"
        footnotes.append((fn_id, fn_text))
        anchor = BeautifulSoup(
            f'<sup id="ref-{fn_id}"><a href="#{fn_id}">[{fn_n}]</a></sup>',
            "html.parser",
        )
        span.replace_with(anchor)

    for span in body.find_all("span"):
        cls = set(span.get("class", []))
        for a in span.find_all("a"):
            a.decompose()
        txt = span.get_text(strip=True)

        if "aaya" in cls:
            span.replace_with(f"﴿{txt}﴾")
        elif "hadith" in cls:
            span.replace_with(txt)
        elif "sora" in cls:
            span.replace_with(PUA_RE.sub("", txt))
        elif "title-2" in cls:
            span.replace_with(BeautifulSoup(f"<h4>{txt}</h4>", "html.parser"))
        elif "title-1" in cls:
            span.replace_with(BeautifulSoup(f"<h5>{txt}</h5>", "html.parser"))

    return body.decode_contents(), footnotes


# ── Scrape All ────────────────────────────────────────────────────────────────
def scrape_all() -> list[Page]:
    urls = discover_urls()
    print(f"\n{len(urls)} صفحة. جاري استخراج المحتوى…\n")
    pages: list[Page] = []

    for i, url in enumerate(urls, 1):
        pid = f"{i:05d}"
        print(f"  [{pid}] {url}")
        soup = fetch(url)
        if not soup:
            continue
        time.sleep(DELAY)

        title = page_title(soup)
        bc    = page_breadcrumb(soup)
        if not bc or bc[-1] != title:
            bc.append(title)

        depth = max(0, len(bc) - SKIP_CRUMBS - 1)
        level = min(depth + 1, 6)

        body_html, footnotes = extract_content(soup, pid)
        pages.append(Page(pid, url, title, level, bc, body_html, footnotes))

    return pages


# ── Build Document Order ──────────────────────────────────────────────────────
def build_document(pages: list[Page]) -> list[Item]:
    section_children: dict[tuple, list[str]] = defaultdict(list)
    for p in pages:
        ancestors = p.breadcrumb[SKIP_CRUMBS:]
        for depth in range(min(len(ancestors) - 1, 4)):
            parent_key = tuple(ancestors[:depth + 1])
            child_name = ancestors[depth + 1] if depth + 1 < len(ancestors) else p.title
            kids = section_children[parent_key]
            if child_name not in kids:
                kids.append(child_name)

    seen_idx: set[tuple] = set()
    idx_n = 0
    result: list[Item] = []

    for p in pages:
        ancestors = p.breadcrumb[SKIP_CRUMBS:]
        for depth in range(min(len(ancestors) - 1, 4)):
            key   = tuple(ancestors[:depth + 1])
            level = depth + 1
            if key not in seen_idx:
                seen_idx.add(key)
                idx_n += 1
                result.append(
                    IndexPage(
                        pid      = f"idx{idx_n:04d}",
                        title    = ancestors[depth],
                        level    = level,
                        children = section_children[key],
                    )
                )
        result.append(p)

    return result


# ── Markdown Export ───────────────────────────────────────────────────────────
def html_to_md(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")

    def walk(node) -> str:
        if isinstance(node, NavigableString):
            return str(node)
        if not isinstance(node, Tag):
            return ""
        name = node.name
        if name in ("script", "style"):
            return ""
        if name == "h4":
            return f"\n\n#### {node.get_text(strip=True)}\n\n"
        if name == "h5":
            return f"\n\n##### {node.get_text(strip=True)}\n\n"
        if name == "p":
            inner = "".join(walk(c) for c in node.children)
            return f"\n\n{inner.strip()}\n\n"
        if name in ("ul", "ol"):
            items = [f"- {li.get_text(strip=True)}" for li in node.find_all("li")]
            return "\n" + "\n".join(items) + "\n\n"
        if name == "br":
            return "  \n"
        if name == "sup":
            return node.get_text()
        return "".join(walk(c) for c in node.children)

    md = walk(soup)
    return re.sub(r"\n{3,}", "\n\n", md).strip()


def _ancestors_to_path(ancestors: list[str]) -> Path:
    parts = [numbered_folder(ancestors, d) for d in range(len(ancestors))]
    return MD_DIR.joinpath(*parts)


def export_markdown(items: list[Item]) -> None:
    MD_DIR.mkdir(parents=True, exist_ok=True)

    for item in items:
        if isinstance(item, Page):
            ancestors = item.breadcrumb[SKIP_CRUMBS:]
            for d in range(len(ancestors) - 1):
                numbered_folder(ancestors, d)

    for item in items:
        if isinstance(item, Page):
            ancestors = item.breadcrumb[SKIP_CRUMBS:]
            folder    = _ancestors_to_path(ancestors[:-1]) if len(ancestors) > 1 else MD_DIR
            folder.mkdir(parents=True, exist_ok=True)

            n_file   = f"{item.pid}_{safe_name(item.title)}.md"
            hashes   = "#" * item.level
            md       = html_to_md(item.body_html)
            fn_block = ""
            if item.footnotes:
                lines    = [f"[^{fid.split('-')[-1]}]: {txt}" for fid, txt in item.footnotes]
                fn_block = "\n\n---\n\n" + "\n".join(lines)
            content = (
                f"{hashes} {item.title}\n\n"
                f"> المصدر: {item.url}\n\n"
                f"{md}{fn_block}\n"
            )
            (folder / n_file).write_text(content, encoding="utf-8")

        elif isinstance(item, IndexPage):
            key = next(
                (k for k, v in _folder_names.items()
                 if k[-1] == item.title and len(k) == item.level),
                None,
            )
            if key:
                folder = MD_DIR.joinpath(
                    *[_folder_names[tuple(key[:d+1])] for d in range(len(key))]
                )
            else:
                folder = MD_DIR / f"{item.pid}_{safe_name(item.title)}"
            folder.mkdir(parents=True, exist_ok=True)

            hashes     = "#" * item.level
            child_type = CHILDREN_NAMES.get(item.level, "قسم")
            phrase     = _count_phrase(len(item.children), child_type)
            bullets    = "\n".join(f"{i}. {c}" for i, c in enumerate(item.children, 1))
            content    = f"{hashes} {item.title}\n\n{phrase}:\n\n{bullets}\n"
            (folder / "_index.md").write_text(content, encoding="utf-8")

    print(f"  → Markdown → {MD_DIR}")


# ── EPUB ──────────────────────────────────────────────────────────────────────
EPUB_CSS = """\
@charset "UTF-8";
body {
    direction: rtl;
    font-family: Amiri, "Traditional Arabic", "Scheherazade New", Arial, sans-serif;
    font-size: 1em;
    line-height: 1.9;
    margin: 1em 2em;
    color: #333;
}
h1,h2,h3,h4,h5,h6 { font-size: 1em; color: #2c3e50; margin: 1em 0 0.4em; font-weight: bold; }
p { margin: 0.4em 0 0.9em; text-align: justify; }
.footnotes { border-top: 1px solid #ccc; margin-top: 2em; padding-top: 0.8em; }
sup a { color: #888; font-size: 0.8em; text-decoration: none; }
ol, ul { margin: 0.4em 0; padding-right: 1.5em; }
"""

_XHTML_TMPL = """\
<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="ar" dir="rtl">
<head>
  <meta charset="utf-8"/>
  <title>{title}</title>
  <link rel="stylesheet" type="text/css" href="../styles/book.css"/>
</head>
<body>
{body}
</body>
</html>"""


def _xhtml(title: str, body: str) -> str:
    return _XHTML_TMPL.format(title=title, body=body)


def _page_xhtml(p: Page) -> str:
    h      = f"<h{p.level}>{p.title}</h{p.level}>"
    fn_sec = ""
    if p.footnotes:
        items = "".join(
            f'<li id="{fid}"><sup>[{fid.split("-")[-1]}]</sup> {txt} '
            f'<a href="#ref-{fid}">↑</a></li>'
            for fid, txt in p.footnotes
        )
        fn_sec = f'<div class="footnotes"><ol>{items}</ol></div>'
    return _xhtml(p.title, f"{h}\n{p.body_html}\n{fn_sec}")


def _index_xhtml(ip: IndexPage) -> str:
    child_type = CHILDREN_NAMES.get(ip.level, "قسم")
    phrase     = _count_phrase(len(ip.children), child_type)
    h          = f"<h{ip.level}>{ip.title}</h{ip.level}>"
    lis        = "".join(f"<li>{c}</li>" for c in ip.children)
    return _xhtml(ip.title, f"{h}\n<p>{phrase}:</p>\n<ol>{lis}</ol>")


def _cover_xhtml(total_pages: int) -> str:
    body = (
        f'<div style="text-align:center;padding:4em 2em">'
        f"<h1>{BOOK_TITLE}</h1>"
        f"<p>عدد الصفحات: {total_pages}</p>"
        f"</div>"
    )
    return _xhtml(BOOK_TITLE, body)


def _build_toc_tree(entries: list[tuple]) -> list[dict]:
    root:  list[dict] = []
    stack: list[tuple[int, list]] = []
    for level, title, pid in entries:
        node = {"level": level, "title": title, "pid": pid, "children": []}
        while stack and stack[-1][0] >= level:
            stack.pop()
        target = stack[-1][1] if stack else root
        target.append(node)
        stack.append((level, node["children"]))
    return root


def _render_ncx(nodes: list[dict], po: list, indent: int = 4) -> list[str]:
    lines, sp = [], " " * indent
    for n in nodes:
        po[0] += 1
        lines += [
            f'{sp}<navPoint id="np-{n["pid"]}" playOrder="{po[0]}">',
            f'{sp}  <navLabel><text>{n["title"]}</text></navLabel>',
            f'{sp}  <content src="pages/p{n["pid"]}.xhtml"/>',
        ]
        if n["children"]:
            lines += _render_ncx(n["children"], po, indent + 2)
        lines.append(f"{sp}</navPoint>")
    return lines


def _render_nav_ol(nodes: list[dict], indent: int = 2) -> list[str]:
    if not nodes:
        return []
    sp, lines = " " * indent, [f"{' '*indent}<ol>"]
    for n in nodes:
        href = f'pages/p{n["pid"]}.xhtml'
        if n["children"]:
            lines.append(f'{sp}  <li><a href="{href}">{n["title"]}</a>')
            lines += _render_nav_ol(n["children"], indent + 4)
            lines.append(f"{sp}  </li>")
        else:
            lines.append(f'{sp}  <li><a href="{href}">{n["title"]}</a></li>')
    lines.append(f"{sp}</ol>")
    return lines


def _nav_xhtml(entries: list[tuple]) -> str:
    tree  = _build_toc_tree(entries)
    inner = "\n".join(_render_nav_ol(tree))
    return f"""\
<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"
      xmlns:epub="http://www.idpf.org/2007/ops"
      xml:lang="ar" dir="rtl">
<head><meta charset="utf-8"/><title>المحتويات</title></head>
<body>
<nav epub:type="toc" id="toc">
  <h1>المحتويات</h1>
{inner}
</nav>
</body>
</html>"""


def export_epub(items: list[Item]) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    uid   = str(uuid.uuid4())
    pages = [i for i in items if isinstance(i, Page)]

    toc_entries: list[tuple] = []
    man_items:   list[str]   = []
    spine_refs:  list[str]   = []

    with zipfile.ZipFile(EPUB_PATH, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            zipfile.ZipInfo("mimetype"),
            "application/epub+zip",
            compress_type=zipfile.ZIP_STORED,
        )
        zf.writestr(
            "META-INF/container.xml",
            '<?xml version="1.0" encoding="utf-8"?>\n'
            '<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">\n'
            '  <rootfiles>\n'
            '    <rootfile full-path="OEBPS/content.opf"'
            ' media-type="application/oebps-package+xml"/>\n'
            '  </rootfiles>\n'
            '</container>',
        )
        zf.writestr("OEBPS/styles/book.css", EPUB_CSS)
        zf.writestr("OEBPS/pages/cover.xhtml", _cover_xhtml(len(pages)))

        man_items = [
            '<item id="ncx"   href="toc.ncx"          media-type="application/x-dtbncx+xml"/>',
            '<item id="nav"   href="nav.xhtml"         media-type="application/xhtml+xml" properties="nav"/>',
            '<item id="css"   href="styles/book.css"   media-type="text/css"/>',
            '<item id="cover" href="pages/cover.xhtml" media-type="application/xhtml+xml"/>',
        ]
        spine_refs = ['<itemref idref="cover"/>']

        for item in items:
            fn  = item.epub_filename()
            iid = f"p{item.pid}"
            if isinstance(item, Page):
                zf.writestr(f"OEBPS/pages/{fn}", _page_xhtml(item))
            else:
                zf.writestr(f"OEBPS/pages/{fn}", _index_xhtml(item))
            man_items.append(
                f'<item id="{iid}" href="pages/{fn}" media-type="application/xhtml+xml"/>'
            )
            spine_refs.append(f'<itemref idref="{iid}"/>')
            if isinstance(item, IndexPage):
                toc_entries.append((item.level, item.title, item.pid))

        manifest = "\n    ".join(man_items)
        spine    = "\n    ".join(spine_refs)
        zf.writestr(
            "OEBPS/content.opf",
            f'<?xml version="1.0" encoding="utf-8"?>\n'
            f'<package xmlns="http://www.idpf.org/2007/opf" version="3.0"'
            f' unique-identifier="uid" xml:lang="ar">\n'
            f'  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">\n'
            f'    <dc:title>{BOOK_TITLE}</dc:title>\n'
            f'    <dc:language>ar</dc:language>\n'
            f'    <dc:identifier id="uid">{uid}</dc:identifier>\n'
            f'  </metadata>\n'
            f'  <manifest>\n    {manifest}\n  </manifest>\n'
            f'  <spine toc="ncx" page-progression-direction="rtl">\n    {spine}\n  </spine>\n'
            f'</package>',
        )

        tree    = _build_toc_tree(toc_entries)
        po      = [0]
        ncx_pts = "\n".join(_render_ncx(tree, po))
        zf.writestr(
            "OEBPS/toc.ncx",
            f'<?xml version="1.0" encoding="utf-8"?>\n'
            f'<!DOCTYPE ncx PUBLIC "-//NISO//DTD ncx 2005-1//EN"'
            f' "http://www.daisy.org/z3986/2005/ncx-2005-1.dtd">\n'
            f'<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">\n'
            f'  <head>\n'
            f'    <meta name="dtb:uid" content="{uid}"/>\n'
            f'    <meta name="dtb:depth" content="6"/>\n'
            f'  </head>\n'
            f'  <docTitle><text>{BOOK_TITLE}</text></docTitle>\n'
            f'  <navMap>\n{ncx_pts}\n  </navMap>\n'
            f'</ncx>',
        )
        zf.writestr("OEBPS/nav.xhtml", _nav_xhtml(toc_entries))

    print(f"  → EPUB  → {EPUB_PATH}")


# ── Main ──────────────────────────────────────────────────────────────────────
def main() -> None:
    mode = f"TEST ({TEST_PAGES} صفحات)" if TEST_PAGES else "FULL (744 صفحة)"
    print(f"=== dorar_osolfeqh_export [{mode}] ===\n")

    print("1) جلب صفحات المقدمة…")
    front = []
    for i, (title, url) in enumerate(FRONT_PAGES, 1):
        pid = f"front{i:02d}"
        print(f"  {pid}: {title}")
        p = fetch_extra_page(title, url, pid, level=1)
        if p:
            front.append(p)

    print("\n2) اكتشاف صفحات الموسوعة…")
    raw_pages = scrape_all()
    print(f"   {len(raw_pages)} صفحة\n")

    print("3) جلب صفحات الملاحق…")
    back = []
    for i, (title, url) in enumerate(BACK_PAGES, 1):
        pid = f"back{i:02d}"
        print(f"  {pid}: {title}")
        p = fetch_extra_page(title, url, pid, level=1)
        if p:
            back.append(p)

    all_pages = front + raw_pages + back

    print(f"\n4) بناء الهيكل…")
    items = build_document(all_pages)
    idx_count = sum(1 for i in items if isinstance(i, IndexPage))
    print(f"   {len(items)} عنصر ({idx_count} فهارس تلقائية)\n")

    print("5) بناء EPUB…")
    export_epub(items)

    print("6) بناء Markdown…")
    export_markdown(items)

    print("\n✓ اكتمل")


if __name__ == "__main__":
    main()
