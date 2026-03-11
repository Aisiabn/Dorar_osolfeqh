#!/usr/bin/env python3
"""
explore_osolfeqh.py — يستكشف بنية dorar.net/osolfeqh
ويقارنها بالأنماط المعروفة من dorar.net/feqhia

الناتج: output/explore_report.txt  +  output/index.html  +  output/sample_*.html
"""

import re
import time
import json
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

# ── Config ────────────────────────────────────────────────────────────────────
START_URL  = "https://dorar.net/osolfeqh"
SAMPLE_N   = 5
DELAY      = 1.0
TIMEOUT    = 20
OUT_DIR    = Path("output")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 6.1; WOW64) AppleWebKit/537.36 "
        "Chrome/109.0.0.0"
    ),
    "Accept-Language": "ar,en-US;q=0.9,en;q=0.8",
    "Referer": "https://dorar.net/",
}

PAGE_RE_CANDIDATES = [
    ("osolfeqh/\\d+", re.compile(r"/osolfeqh/(\d+)")),
    ("feqhia/\\d+",   re.compile(r"/feqhia/(\d+)")),
]

# ── HTTP ──────────────────────────────────────────────────────────────────────
_s = requests.Session()
_s.headers.update(HEADERS)


def fetch(url: str) -> BeautifulSoup | None:
    try:
        r = _s.get(url, timeout=TIMEOUT)
        r.raise_for_status()
        r.encoding = "utf-8"
        return BeautifulSoup(r.text, "html.parser")
    except Exception as e:
        return None


def fetch_raw(url: str) -> str | None:
    try:
        r = _s.get(url, timeout=TIMEOUT)
        r.raise_for_status()
        r.encoding = "utf-8"
        return r.text
    except Exception:
        return None


# ── Checks ────────────────────────────────────────────────────────────────────
def check_index_page(soup: BeautifulSoup, raw: str, report: list[str]) -> list[str]:
    report.append("\n" + "="*60)
    report.append(f"URL: {START_URL}")
    report.append("="*60)

    mtree = soup.find("ul", id="mtree")
    report.append(f"\n[A] ul#mtree موجود؟  {'✓ نعم' if mtree else '✗ لا'}")

    tree_alts = [
        ("ul.dorar_accordion_treeview", soup.find("ul", class_="dorar_accordion_treeview")),
        ("ul.tree",                     soup.find("ul", class_="tree")),
        ("nav#sidebar",                 soup.find("nav", id="sidebar")),
        ("div#sidebar",                 soup.find("div", id="sidebar")),
        ("#toc",                        soup.find(id="toc")),
    ]
    report.append("\n[B] بدائل شجرة الفهرس:")
    for name, el in tree_alts:
        if el:
            links = el.find_all("a", href=True)
            report.append(f"    ✓ {name} — {len(links)} رابط")

    report.append("\n[C] أنماط روابط الصفحات الداخلية:")
    found_urls = []
    for pat_name, pat_re in PAGE_RE_CANDIDATES:
        matches = pat_re.findall(raw)
        unique  = sorted(set(matches), key=int) if matches else []
        report.append(f"    {pat_name}: {len(unique)} رابط فريد "
                      f"{'— مثال: ' + unique[0] if unique else ''}")
        if unique and not found_urls:
            found_urls = [f"https://dorar.net/osolfeqh/{i}" for i in unique]

    all_links = [a["href"] for a in soup.find_all("a", href=re.compile(r"/osolfeqh/\d+"))]
    report.append(f"\n[D] روابط /osolfeqh/NUMBER: {len(all_links)}")
    if all_links:
        report.append(f"    أول 5: {all_links[:5]}")

    og = soup.find("meta", property="og:title")
    report.append(f"\n[E] og:title: {og['content'] if og else '—'}")

    bc = soup.find("ol", class_="breadcrumb")
    report.append(f"\n[F] ol.breadcrumb: {'✓' if bc else '✗'}")

    cntnt = soup.find("div", id="cntnt")
    report.append(f"\n[G] div#cntnt: {'✓ ' + str(len(cntnt.get_text())) + ' حرف' if cntnt else '✗'}")

    if not found_urls and all_links:
        found_urls = [urljoin("https://dorar.net", h) for h in all_links]

    return found_urls


def check_inner_page(url: str, idx: int, report: list[str]) -> dict:
    soup = fetch(url)
    info = {"url": url, "ok": bool(soup)}
    if not soup:
        report.append(f"\n  [{idx}] ✗ فشل الجلب: {url}")
        return info

    report.append(f"\n  [{idx}] {url}")

    og = soup.find("meta", property="og:title")
    info["og_title"] = og["content"] if og else None
    report.append(f"       og:title   → {info['og_title']}")

    bc = soup.find("ol", class_="breadcrumb")
    if bc:
        crumbs = [li.get_text(strip=True) for li in bc.find_all("li")]
        info["breadcrumb"] = crumbs
        report.append(f"       breadcrumb → {' > '.join(crumbs)}")
    else:
        info["breadcrumb"] = []
        report.append("       breadcrumb → ✗ غير موجود")

    cntnt = soup.find("div", id="cntnt")
    if cntnt:
        txt = cntnt.get_text(strip=True)
        info["cntnt_len"]     = len(txt)
        info["cntnt_preview"] = txt[:120]
        report.append(f"       div#cntnt  → ✓ {len(txt)} حرف")
        report.append(f"                    «{txt[:100]}…»")
    else:
        info["cntnt_len"] = 0
        report.append("       div#cntnt  → ✗ غير موجود")
        divs = [(d.get("id") or d.get("class"), len(d.get_text()))
                for d in soup.find_all("div") if len(d.get_text()) > 200]
        divs.sort(key=lambda x: -x[1])
        if divs:
            report.append(f"       أكبر div   → {divs[0]}")

    for cls in ("aaya", "hadith", "sora", "tip", "title-1", "title-2"):
        n = len(soup.find_all("span", class_=cls))
        if n:
            report.append(f"       span.{cls:<10} → {n}")

    tips = soup.find_all("span", class_="tip")
    info["footnote_count"] = len(tips)
    if tips:
        report.append(f"       footnotes  → {len(tips)}")

    nav_next = soup.find("a", string=re.compile("التالي"))
    nav_prev = soup.find("a", string=re.compile("السابق"))
    info["has_next"] = bool(nav_next)
    info["has_prev"] = bool(nav_prev)
    if nav_next:
        report.append(f"       التالي     → {nav_next.get('href')}")

    return info


def guess_skip_crumbs(samples: list[dict]) -> int:
    all_bc = [s["breadcrumb"] for s in samples if s.get("breadcrumb")]
    if not all_bc:
        return 0
    min_len = min(len(bc) for bc in all_bc)
    skip = 0
    for i in range(min_len):
        if len({bc[i] for bc in all_bc}) == 1:
            skip = i + 1
        else:
            break
    return skip


# ── Main ──────────────────────────────────────────────────────────────────────
def main() -> None:
    OUT_DIR.mkdir(exist_ok=True)
    report: list[str] = ["=== استكشاف dorar.net/osolfeqh ===\n"]

    print("جلب الصفحة الرئيسية…")
    raw  = fetch_raw(START_URL)
    soup = BeautifulSoup(raw, "html.parser") if raw else None

    if not soup:
        print("✗ فشل جلب الصفحة الرئيسية")
        return

    (OUT_DIR / "index.html").write_text(raw, encoding="utf-8")
    report.append("HTML محفوظ في output/index.html\n")

    found_urls = check_index_page(soup, raw, report)

    report.append("\n\n" + "="*60)
    report.append(f"فحص {min(SAMPLE_N, len(found_urls))} صفحات داخلية")
    report.append("="*60)

    samples = []
    for i, url in enumerate(found_urls[:SAMPLE_N], 1):
        info = check_inner_page(url, i, report)
        samples.append(info)
        raw_inner = fetch_raw(url)
        if raw_inner:
            pid = url.rstrip("/").split("/")[-1]
            (OUT_DIR / f"sample_{pid}.html").write_text(raw_inner, encoding="utf-8")
        time.sleep(DELAY)

    skip = guess_skip_crumbs(samples)
    report.append(f"\n\n[H] SKIP_CRUMBS المقترح: {skip}")
    report.append(f"    (feqhia كانت 2 = 'الرئيسة' + 'الموسوعة الفقهية')")

    report.append("\n\n" + "="*60)
    report.append("ملخص — ما تحتاج تغييره في الكود النهائي")
    report.append("="*60)

    has_mtree = bool(soup.find("ul", id="mtree"))
    has_cntnt = any(s.get("cntnt_len", 0) > 0 for s in samples)
    has_bc    = any(s.get("breadcrumb") for s in samples)

    report.append(f"""
  START_URL   = "https://dorar.net/osolfeqh"
  PAGE_RE     = re.compile(r"/osolfeqh/(\\d+)")   ← تحقق من [C]
  SKIP_CRUMBS = {skip}                             ← من [H]

  ul#mtree  → {"✓ نفس feqhia" if has_mtree else "✗ راجع [B]"}
  div#cntnt → {"✓ نفس feqhia" if has_cntnt else "✗ راجع sample_*.html"}
  breadcrumb→ {"✓ نفس feqhia" if has_bc    else "✗ راجع sample_*.html"}
""")

    (OUT_DIR / "explore_samples.json").write_text(
        json.dumps(samples, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    txt = "\n".join(report)
    (OUT_DIR / "explore_report.txt").write_text(txt, encoding="utf-8")
    print(txt)
    print("\n✓ التقرير في output/explore_report.txt")


if __name__ == "__main__":
    main()
