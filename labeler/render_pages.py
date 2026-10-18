"""Screenshot each queued page's first screen and measure whether it still matches its capture.

The corpus was captured without pixels (media_suppressed_browser_state), and its collector changed each page
before measuring it: capture_media_safety.js (copied from the collector) forces Arial, removes background images,
shadows and pseudo-content, and hides media with their sources removed; image, media and font requests and all
frames were blocked. This renders the live URL under those same conditions (1365x900, scale 1, JavaScript on,
same-site requests only, no downloads or service workers), so the screenshot can line up with the captured
geometry; media show as the script's grey placeholders. It saves the first screen as a JPEG and scores drift:

  anchors  captured elements in the first screen whose tag + own text is unique on the page
  found    anchors also present (same tag + text) on the live page
  aligned  found anchors at the captured position within TOLERANCE px, after removing one common vertical
           offset (e.g. a cookie banner pushing everything down)
  score    aligned / anchors

Results go to runs/corpus/renders/index.json; screenshots to runs/corpus/renders/<site>/<page>.jpg, and with
--check, an overlay (<page>.check.jpg) with aligned anchors in green and drifted ones in red.

Run with Playwright and your installed Chrome (no browser download):
  uv run --with playwright==1.62.0 --with pillow python labeler/render_pages.py --count 30 --check   # the capture used 1.62
"""
import argparse
from datetime import datetime, timezone
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import statistics
import sys
import time
from urllib.parse import urlsplit

APP = Path(__file__).resolve().parent
sys.path.insert(0, str(APP))
from queue_order import CORPUS, STATE  # noqa: E402

RENDERS = CORPUS / "renders"
CAPTURES = CORPUS / "public-research-v1/captures"
TOLERANCE = 4
PASS_SCORE = 0.8
SUPPRESSION = APP / "capture_media_safety.js"
# The collector's media_safety.block_request: media resource types and media file extensions never load.
MEDIA_TYPES = {"image", "media", "font", "texttrack", "object", "embed"}
MEDIA_FILE = re.compile(r"\.(?:svg|png|jpe?g|gif|webp|avif|ico|bmp|tiff?|mp[34]|webm|ogg|wav|woff2?|ttf|otf)(?:$|[?#])", re.I)
VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}

# Each visible element's tag, own (direct) text and page position on the live page.
LIVE_ELEMENTS_JS = r"""
() => [...document.querySelectorAll('body *')].map(el => {
  const text = [...el.childNodes].filter(n => n.nodeType === 3).map(n => n.data).join(' ').replace(/\s+/g, ' ').trim();
  const r = el.getBoundingClientRect();
  return { tag: el.localName, text: text.slice(0, 120), box: [r.x + scrollX, r.y + scrollY, r.width, r.height] };
}).filter(e => e.text && e.box[2] > 0 && e.box[3] > 0)
"""


class _OwnText(HTMLParser):
    """capture id -> (tag, own text) from document.html, where every element carries data-sr-capture-id."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack, self.found = [], {}

    def handle_starttag(self, tag, attrs):
        capture_id = dict(attrs).get("data-sr-capture-id")
        if tag in VOID:
            if capture_id:
                self.found[capture_id] = [tag, ""]
            return
        self.stack.append((tag, capture_id))
        if capture_id:
            self.found[capture_id] = [tag, ""]

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                del self.stack[i:]
                return

    def handle_data(self, data):
        if self.stack and self.stack[-1][1] and self.stack[-1][0] not in {"script", "style"}:
            self.found[self.stack[-1][1]][1] += " " + data


def norm(text):
    return " ".join(text.split())[:120]


def unique_keys(items):
    """{(tag, text): box} for keys that occur exactly once."""
    seen, out = {}, {}
    for tag, text, box in items:
        key = (tag, text)
        seen[key] = seen.get(key, 0) + 1
        out[key] = box
    return {k: v for k, v in out.items() if seen[k] == 1}


def captured_anchors(state_dir, viewport):
    """Unique tag + own text elements in the capture's first screen, with their captured boxes."""
    parser = _OwnText()
    parser.feed((state_dir / "document.html").read_text(encoding="utf-8", errors="replace"))
    geometry = json.loads((state_dir / "geometry.json").read_text())
    boxes = {row["dom_id"]: row["bounds"] for row in geometry.get("elements_and_text", []) if row.get("dom_id") and row.get("bounds")}
    items = [(tag, norm(text), boxes[cid]) for cid, (tag, text) in parser.found.items() if cid in boxes]
    everything = unique_keys([i for i in items if len(i[1]) >= 2])
    return {k: b for k, b in everything.items() if b[2] > 0 and b[3] > 0 and b[1] < viewport["height"] and b[1] + b[3] > 0}


def drift(anchors, live):
    """Compare captured anchors with live elements: {anchors, found, aligned, offset, score, misaligned}."""
    live_boxes = unique_keys([(e["tag"], norm(e["text"]), e["box"]) for e in live])
    common = [k for k in anchors if k in live_boxes]
    if not anchors:
        return {"anchors": 0, "found": 0, "aligned": 0, "offset": 0, "score": None, "misaligned": []}
    offset = statistics.median(live_boxes[k][1] - anchors[k][1] for k in common) if common else 0
    aligned, misaligned = [], []
    for k in common:
        (cx, cy, cw, ch), (lx, ly, lw, lh) = anchors[k], live_boxes[k]
        same = abs(lx - cx) <= TOLERANCE and abs(ly - cy - offset) <= TOLERANCE and abs(lw - cw) <= TOLERANCE * 2
        (aligned if same else misaligned).append(k)
    return {"anchors": len(anchors), "found": len(common), "aligned": len(aligned), "offset": round(offset),
            "score": round(len(aligned) / len(anchors), 3), "misaligned": [list(k) for k in misaligned[:20]]}


def blocked_like_capture(resource_type, url, site_url, main_frame):
    """True when the collector would have refused this request (so the live layout matches the capture's)."""
    return (not main_frame or resource_type in MEDIA_TYPES or bool(MEDIA_FILE.search(url))
            or not same_site(url, site_url))


def same_site(url, site_url):
    """Requests the capture would also have allowed: the page's own host or its subdomains (and inline data)."""
    scheme, host = urlsplit(url).scheme, (urlsplit(url).hostname or "")
    if scheme in {"data", "blob", "about"}:
        return True
    base = (urlsplit(site_url).hostname or "").removeprefix("www.")
    return host == base or host.endswith("." + base)


def render(browser, page_id, out_dir):
    state = CAPTURES / page_id / STATE
    capture = json.loads((state / "capture.json").read_text())
    viewport = json.loads((state / "environment.json").read_text()).get("viewport") or {"width": 1365, "height": 900}
    url = capture["final_url"]
    entry = {"url": url, "rendered_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    context = browser.new_context(viewport=viewport, device_scale_factor=1, java_script_enabled=True,
                                  service_workers="block", accept_downloads=False, locale="en-US", timezone_id="UTC")
    blocked = [0]
    # A handler that never connects leaves sockets mocked (no traffic). Don't call socket.close() here:
    # the sync API deadlocks inside its own event-loop callback.
    context.route_web_socket("**/*", lambda socket: None)
    context.add_init_script(path=str(SUPPRESSION))
    page = context.new_page()

    def route(r):
        if blocked_like_capture(r.request.resource_type, r.request.url, url, r.request.frame == page.main_frame):
            blocked[0] += 1
            return r.abort()
        return r.continue_()

    context.route("**/*", route)
    started = time.monotonic()
    try:
        response = page.goto(url, wait_until="domcontentloaded", timeout=15000)
        entry["http_status"] = response.status if response else None
        try:
            page.wait_for_load_state("networkidle", timeout=5000)
        except Exception:
            pass
        page.wait_for_timeout(500)
        # The script's own pre-capture step: grey placeholders where media sit.
        page.evaluate("() => window.__semanticMediaSafety && window.__semanticMediaSafety.prepare()")
        entry["final_url"] = page.url
        image = out_dir / f"{page_id}.jpg"
        image.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(image), type="jpeg", quality=80, full_page=False)
        live = page.evaluate(LIVE_ELEMENTS_JS)
        entry.update(drift(captured_anchors(state, viewport), live))
        if entry.get("http_status") and entry["http_status"] >= 400:
            entry["status"] = "failed"
        elif entry["score"] is None:
            entry["status"] = "no_anchors"
        else:
            entry["status"] = "ok" if entry["score"] >= PASS_SCORE else "drifted"
    except Exception as error:
        entry.update(status="failed", error=str(error).splitlines()[0][:300])
    finally:
        entry["seconds"] = round(time.monotonic() - started, 1)
        entry["requests_blocked"] = blocked[0]
        context.close()
    return entry


def check_overlay(page_id, entry, out_dir):
    """Screenshot with the captured anchors drawn on it: green aligned, red drifted, grey missing live."""
    from PIL import Image, ImageDraw
    state = CAPTURES / page_id / STATE
    viewport = json.loads((state / "environment.json").read_text()).get("viewport")
    anchors = captured_anchors(state, viewport)
    bad = {tuple(k) for k in entry.get("misaligned", [])}
    image = Image.open(out_dir / f"{page_id}.jpg").convert("RGB")
    draw = ImageDraw.Draw(image)
    for key, (x, y, w, h) in anchors.items():
        color = "#e53935" if key in bad else "#43a047"
        draw.rectangle([x, y, x + w, y + h], outline=color, width=2)
    image.save(out_dir / f"{page_id}.check.jpg", quality=80)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--group", default="main")
    parser.add_argument("--count", type=int, default=30)
    parser.add_argument("--start", type=int, default=0, help="queue position to start from (0 = first)")
    parser.add_argument("--force", action="store_true", help="re-render pages already in the index")
    parser.add_argument("--check", action="store_true", help="also write <page>.check.jpg overlays")
    args = parser.parse_args()
    from playwright.sync_api import sync_playwright

    queue = json.loads((CORPUS / "queue.json").read_text())
    pages = [e["page"] for e in queue["groups"][args.group][args.start:args.start + args.count]]
    index_path = RENDERS / "index.json"
    index = json.loads(index_path.read_text()) if index_path.exists() else {}
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="chrome", headless=True)
        for n, page_id in enumerate(pages, 1):
            if page_id in index and not args.force:
                continue
            entry = render(browser, page_id, RENDERS)
            if args.check and entry["status"] in {"ok", "drifted"}:
                check_overlay(page_id, entry, RENDERS)
            index[page_id] = entry
            RENDERS.mkdir(parents=True, exist_ok=True)
            index_path.with_suffix(".tmp").write_text(json.dumps(index, indent=1))
            index_path.with_suffix(".tmp").replace(index_path)
            print(f"{n:3d}/{len(pages)} {entry['status']:10s} score={entry.get('score')} found={entry.get('found')}/{entry.get('anchors')} "
                  f"offset={entry.get('offset')} {entry['seconds']}s {entry['url'][:70]}", flush=True)
        browser.close()
    done = [index[p] for p in pages if p in index]
    counts = {s: sum(e["status"] == s for e in done) for s in ("ok", "drifted", "failed", "no_anchors")}
    print("summary:", counts)


if __name__ == "__main__":
    main()
