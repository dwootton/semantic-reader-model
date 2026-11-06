"""Save a styled, static copy of each queued page that the labeler can show and click into.

The capture kept no pixels or styling. This loads the live URL with its own CSS, images and fonts (no media,
frames or websockets), then snapshot_page.js matches live elements to the captured document by content and
stamps them with the capture's src-<base36> ids, marks clickable elements (data-sr-click), freezes form state
and removes scripts. Here, stylesheets, images and fonts the page loaded are inlined as text and data: URIs,
and viewport-height units are pinned to the capture's 900 px viewport, so the copy can be shown at full
height in a sandboxed frame with no scripts and no network.

  matched  compressed-DOM nodes found (and stamped) in the live page, by content
  score    matched / compressed-DOM nodes

The live page is today's page, not the capture: nodes that changed or disappeared are simply not matched.
Copies go to runs/corpus/snapshots/<site>/<page>.html (private, with third-party assets); results to
runs/corpus/snapshots/index.json.

  uv run --with playwright==1.62.0 python labeler/snapshot_pages.py --count 5
"""
import argparse
import base64
from datetime import datetime, timezone
import html
import json
from pathlib import Path
import re
import sys
import time
from urllib.parse import urljoin, urldefrag

APP = Path(__file__).resolve().parent
sys.path.insert(0, str(APP))
from queue_order import CORPUS, STATE  # noqa: E402

SNAPSHOTS = CORPUS / "snapshots"
CAPTURES = CORPUS / "public-research-v1/captures"
SNAPSHOT_JS = (APP / "snapshot_page.js").read_text()
VIEWPORT = {"width": 1365, "height": 900}
MAX_ASSET = 3 << 20      # larger single images/fonts are left out
MAX_INLINED = 25 << 20   # per page
# Elements with click listeners, which leave no trace in the HTML. Runs before the page's own scripts.
CLICK_LISTENERS = """
(() => { const add = EventTarget.prototype.addEventListener;
  EventTarget.prototype.addEventListener = function (type, ...rest) {
    if (this instanceof Element && /^(click|mousedown|mouseup|pointerdown|pointerup|touchstart)$/.test(type)) this.__srClick = true;
    return add.call(this, type, ...rest); }; })();
"""

VH = re.compile(r"(-?\d*\.?\d+)[dsl]?vh\b")
URL = re.compile(r"""url\(\s*(['"]?)(.*?)\1\s*\)""", re.S)
IMPORT = re.compile(r"""@import\s+(?:url\(\s*)?(['"]?)([^'")\s;]+)\1\s*\)?\s*([^;]*);""")


def pin_vh(css, height=VIEWPORT["height"]):
    """100vh -> 900px: the copy is shown at full page height, where viewport units would stretch."""
    return VH.sub(lambda m: f"{float(m[1]) * height / 100:g}px", css)


def data_uri(asset):
    kind, body = asset
    return f"data:{kind};base64,{base64.b64encode(body).decode()}"


def inline_css(css, base, assets, budget, depth=0):
    """Pin vh, inline @imports (to a small depth) and swap url() references for data: URIs we have."""
    css = pin_vh(css)
    if depth < 3:
        def imported(m):
            url = urljoin(base, m[2])
            asset = assets.get(urldefrag(url)[0])
            if not asset:
                return ""
            body = inline_css(asset[1].decode("utf-8", "replace"), url, assets, budget, depth + 1)
            return f"@media {m[3].strip()} {{\n{body}\n}}" if m[3].strip() else body
        css = IMPORT.sub(imported, css)

    def swap(m):
        url = m[2].strip()
        if url.startswith(("data:", "#")) or not url:
            return m[0]
        asset = assets.get(urldefrag(urljoin(base, url))[0])
        if asset and len(asset[1]) <= MAX_ASSET and budget[0] >= len(asset[1]):
            budget[0] -= len(asset[1])
            return f'url("{data_uri(asset)}")'
        return 'url("data:,")'  # not loaded; an empty data: URL fails quietly and keeps the copy offline
    return URL.sub(swap, css)


def inline_page(page_html, page_url, assets):
    """Fill <style data-sr-href> from the loaded stylesheets, process every <style> and style attribute, and
    swap media src/poster/href attributes for data: URIs."""
    budget = [MAX_INLINED]

    def style_block(m):
        attrs, body = m[1], m[2]
        href = re.search(r'data-sr-href="([^"]*)"', attrs)
        if href:
            url = html.unescape(href[1])
            asset = assets.get(urldefrag(url)[0])
            css = inline_css(asset[1].decode("utf-8", "replace"), url, assets, budget) if asset else ""
        else:
            css = inline_css(body, page_url, assets, budget)
        css = css.replace("</style", "<\\/style")
        return f"<style{attrs}>{css}</style>"
    out = re.sub(r"<style([^>]*)>(.*?)</style>", style_block, page_html, flags=re.S | re.I)

    def style_attr(m):
        css = inline_css(html.unescape(m[1]), page_url, assets, budget)
        return f' style="{html.escape(css, quote=True)}"'
    out = re.sub(r' style="([^"]*)"', style_attr, out)

    def media_attr(m):
        url = urldefrag(urljoin(page_url, html.unescape(m[2])))[0]
        asset = assets.get(url)
        if asset and asset[0].startswith("image/") and len(asset[1]) <= MAX_ASSET and budget[0] >= len(asset[1]):
            budget[0] -= len(asset[1])
            return f' {m[1]}="{data_uri(asset)}"'
        return m[0] if m[1] == "href" else f' {m[1]}="data:,"'
    return re.sub(r' (src|poster|href|xlink:href)="([^"]*)"', media_attr, out)


def asset_kind(response):
    kind = (response.headers.get("content-type") or "").split(";")[0].strip().lower()
    url = response.url.lower().split("?")[0]
    if kind.startswith(("image/", "font/")) or kind == "text/css":
        return kind
    for ext, guess in ((".css", "text/css"), (".woff2", "font/woff2"), (".woff", "font/woff"), (".ttf", "font/ttf"),
                       (".otf", "font/otf"), (".svg", "image/svg+xml"), (".png", "image/png"), (".jpg", "image/jpeg"),
                       (".jpeg", "image/jpeg"), (".gif", "image/gif"), (".webp", "image/webp")):
        if url.endswith(ext):
            return guess
    return "application/font-woff" if "font" in kind else None


def compact_ids(state):
    compact = (state / "compression/document-00000.html").read_text(encoding="utf-8", errors="replace")
    return {f"src-{ref}" for ref in re.findall(r'data-r="([0-9a-z]+)"', compact)}


def snapshot(browser, page_id):
    state = CAPTURES / page_id / STATE
    url = json.loads((state / "capture.json").read_text())["final_url"]
    entry = {"url": url, "snapped_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    context = browser.new_context(viewport=VIEWPORT, device_scale_factor=1, service_workers="block",
                                  accept_downloads=False, locale="en-US", timezone_id="UTC")
    context.route_web_socket("**/*", lambda socket: None)  # mocked; never call socket methods here (deadlock)
    context.add_init_script(CLICK_LISTENERS)
    page = context.new_page()
    context.route("**/*", lambda r: r.abort() if r.request.resource_type in {"media", "websocket"} or
                  (r.request.resource_type == "document" and r.request.frame != page.main_frame) else r.continue_())
    responses = []
    page.on("response", lambda r: responses.append(r))  # bodies are read after loading, outside the callback
    started = time.monotonic()
    try:
        response = page.goto(url, wait_until="domcontentloaded", timeout=20000)
        entry["http_status"] = response.status if response else None
        try:
            page.wait_for_load_state("networkidle", timeout=8000)
        except Exception:
            pass
        # Scroll through once so lazy images load, then return to the top.
        page.evaluate("""async () => { for (let y = 0; y < Math.min(document.body.scrollHeight, 20000); y += 800) {
          scrollTo(0, y); await new Promise(r => setTimeout(r, 120)); } scrollTo(0, 0); }""")
        try:
            page.wait_for_load_state("networkidle", timeout=4000)
        except Exception:
            pass
        result = page.evaluate(SNAPSHOT_JS, (state / "document.html").read_text(encoding="utf-8", errors="replace"))
        assets = {}
        for r in responses:
            kind = asset_kind(r)
            if kind and r.ok and urldefrag(r.url)[0] not in assets:
                try:
                    assets[urldefrag(r.url)[0]] = (kind, r.body())
                except Exception:
                    pass  # body evicted or a redirect
        copy = inline_page(result["html"], page.url, assets)
        out = SNAPSHOTS / f"{page_id}.html"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(copy, encoding="utf-8")
        wanted = compact_ids(state)
        matched = len(wanted & set(result["ids"]))
        entry.update(final_url=page.url, height=result["height"], clickable=result["clickable"], stamped=result["stamped"],
                     compact=len(wanted), matched=matched, score=round(matched / len(wanted), 3) if wanted else None,
                     bytes=len(copy.encode()))
        entry["status"] = "failed" if (entry["http_status"] or 0) >= 400 else "ok"
    except Exception as error:
        entry.update(status="failed", error=str(error).splitlines()[0][:300])
    finally:
        entry["seconds"] = round(time.monotonic() - started, 1)
        context.close()
    return entry


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--group", default="main")
    parser.add_argument("--count", type=int, default=5)
    parser.add_argument("--start", type=int, default=0, help="queue position to start from (0 = first)")
    parser.add_argument("--page", action="append", help="a <site>/<page> id instead of queue positions (repeatable)")
    parser.add_argument("--force", action="store_true", help="redo pages already in the index")
    args = parser.parse_args()
    from playwright.sync_api import sync_playwright

    queue = json.loads((CORPUS / "queue.json").read_text())
    pages = args.page or [e["page"] for e in queue["groups"][args.group][args.start:args.start + args.count]]
    index_path = SNAPSHOTS / "index.json"
    index = json.loads(index_path.read_text()) if index_path.exists() else {}
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="chrome", headless=True)
        for n, page_id in enumerate(pages, 1):
            if page_id in index and not args.force:
                continue
            entry = snapshot(browser, page_id)
            index[page_id] = entry
            SNAPSHOTS.mkdir(parents=True, exist_ok=True)
            index_path.with_suffix(".tmp").write_text(json.dumps(index, indent=1))
            index_path.with_suffix(".tmp").replace(index_path)
            print(f"{n:3d}/{len(pages)} {entry['status']:7s} matched={entry.get('matched')}/{entry.get('compact')} "
                  f"clickable={entry.get('clickable')} {round(entry.get('bytes', 0) / 1e6, 1)}MB {entry['seconds']}s {entry['url'][:70]}",
                  flush=True)
        browser.close()


if __name__ == "__main__":
    main()
