"""信息精选系统 - 采集层 v2
修复所有源 + RSSHub 代理 + 批量处理"""
import json
import re
import hashlib
import time
from datetime import datetime
import feedparser
import requests
from bs4 import BeautifulSoup
import config
import db

# RSSHub 公共实例（可替换为自建）
RSSHUB_BASE = "https://rsshub.app"


def _clean_html(html):
    if not html:
        return ""
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "nav", "footer", "header"]):
        tag.decompose()
    text = soup.get_text(separator="\n", strip=True)
    return re.sub(r'\n{3,}', '\n\n', text).strip()


def _word_count(text):
    if not text:
        return 0
    return len(re.findall(r'[\u4e00-\u9fff]', text)) + len(re.findall(r'[a-zA-Z]+', text))


def _make_external_id(url, title):
    raw = (url or "") + (title or "")
    return hashlib.md5(raw.encode()).hexdigest()[:16]


def _fetch_url(url, timeout=None):
    timeout = timeout or config.FETCH_TIMEOUT
    headers = {"User-Agent": config.USER_AGENT}
    try:
        resp = requests.get(url, headers=headers, timeout=timeout, allow_redirects=True)
        resp.raise_for_status()
        return resp.text
    except Exception as e:
        print(f"  [WARN] fetch {url}: {e}")
        return None


def _fetch_json(url, timeout=None):
    timeout = timeout or config.FETCH_TIMEOUT
    headers = {"User-Agent": config.USER_AGENT}
    try:
        resp = requests.get(url, headers=headers, timeout=timeout)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        print(f"  [WARN] fetch json {url}: {e}")
        return None


def _parse_feed(url):
    """解析 RSS feed，处理 XML 不规范的情况"""
    try:
        feed = feedparser.parse(url, agent=config.USER_AGENT)
        if feed.entries:
            return feed
    except Exception:
        pass

    # feedparser 失败，尝试手动修复 XML
    raw = _fetch_url(url)
    if not raw:
        return None
    # 移除非法 XML 字符
    raw = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', raw)
    # 修复常见的未闭合标签
    raw = re.sub(r'<br(?!\s*/)>', '<br/>', raw, flags=re.IGNORECASE)
    raw = re.sub(r'<hr(?!\s*/)>', '<hr/>', raw, flags=re.IGNORECASE)
    raw = re.sub(r'<img([^>]*?)(?<!/)>', r'<img\1/>', raw, flags=re.IGNORECASE)
    try:
        feed = feedparser.parse(raw)
        return feed if feed.entries else None
    except Exception:
        return None


def _save_items(conn, source_id, items):
    """批量保存内容条目"""
    count = 0
    for item in items:
        title = (item.get("title") or "").strip()
        link = item.get("link") or ""
        author = item.get("author") or ""
        content = item.get("content") or ""
        published = item.get("published") or ""
        content_type = item.get("content_type", "text")

        if not content or len(content) < 30:
            continue

        ext_id = _make_external_id(link, title) or hashlib.md5(title.encode()).hexdigest()[:16]
        wc = _word_count(content)
        new_id = db.upsert_content(
            conn, source_id, ext_id, title, link, author,
            content[:8000], content_type, published[:25] if published else None, wc
        )
        if new_id:
            count += 1
    return count


# ============================================================
#  RSS 通用采集
# ============================================================
def collect_rss(source):
    cfg = json.loads(source["fetch_config"]) if source["fetch_config"] else {}
    rss_url = cfg.get("rss") or source["url"]
    if not rss_url:
        return 0

    print(f"  [RSS] {source['name']} → {rss_url}")
    feed = _parse_feed(rss_url)
    if not feed or not feed.entries:
        print(f"  [ERR] no entries")
        return 0

    items = []
    for entry in feed.entries[:20]:
        title = entry.get("title", "").strip()
        link = entry.get("link", "").strip()
        author = entry.get("author", "").strip()
        published = entry.get("published") or entry.get("updated") or ""

        content = ""
        if hasattr(entry, "content") and entry.content:
            content = _clean_html(entry.content[0].get("value", ""))
        elif hasattr(entry, "summary"):
            content = _clean_html(entry.summary)
        elif hasattr(entry, "description"):
            content = _clean_html(entry.description)

        if not content or len(content) < 50:
            if link:
                full = _fetch_url(link)
                if full:
                    content = _clean_html(full)[:5000]

        items.append({
            "title": title, "link": link, "author": author,
            "content": content, "published": published,
        })

    conn = db.get_db()
    n = _save_items(conn, source["id"], items)
    conn.close()
    print(f"  → 新增 {n} 条")
    return n


# ============================================================
#  RSSHub 代理采集
# ============================================================
def collect_rsshub(source):
    """通过 RSSHub 采集（雪球、Twitter 等）"""
    cfg = json.loads(source["fetch_config"]) if source["fetch_config"] else {}
    rsshub_path = cfg.get("rsshub_path", "")
    if not rsshub_path:
        return 0

    rss_url = f"{RSSHUB_BASE}{rsshub_path}"
    print(f"  [RSSHub] {source['name']} → {rss_url}")
    feed = _parse_feed(rss_url)
    if not feed or not feed.entries:
        print(f"  [ERR] no entries from RSSHub")
        return 0

    items = []
    for entry in feed.entries[:15]:
        title = entry.get("title", "").strip()
        link = entry.get("link", "").strip()
        author = entry.get("author", "").strip()
        published = entry.get("published") or entry.get("updated") or ""

        content = ""
        if hasattr(entry, "content") and entry.content:
            content = _clean_html(entry.content[0].get("value", ""))
        elif hasattr(entry, "summary"):
            content = _clean_html(entry.summary)

        items.append({
            "title": title, "link": link, "author": author,
            "content": content, "published": published,
        })

    conn = db.get_db()
    n = _save_items(conn, source["id"], items)
    conn.close()
    print(f"  → 新增 {n} 条")
    return n


# ============================================================
#  Paul Graham（scrape）
# ============================================================
def collect_paul_graham(source):
    print(f"  [SCRAPE] {source['name']}")
    html = _fetch_url("https://paulgraham.com/articles.html")
    if not html:
        return 0

    soup = BeautifulSoup(html, "lxml")
    links = soup.find_all("a")
    items = []
    for a in links[:30]:
        href = a.get("href", "")
        title = a.get_text(strip=True)
        if not title or len(title) < 5:
            continue
        if not href.startswith("http"):
            href = f"https://paulgraham.com/{href}"

        # 抓全文
        content = _fetch_url(href)
        if content:
            content = _clean_html(content)[:5000]
        items.append({
            "title": title, "link": href, "author": "Paul Graham",
            "content": content or "", "published": "",
        })

    conn = db.get_db()
    n = _save_items(conn, source["id"], items)
    conn.close()
    print(f"  → 新增 {n} 条")
    return n


# ============================================================
#  Hacker News API
# ============================================================
def collect_hackernews(source):
    print(f"  [HN] {source['name']}")
    story_ids = _fetch_json("https://hacker-news.firebaseio.com/v0/topstories.json")
    if not story_ids:
        return 0

    items = []
    for sid in story_ids[:20]:
        story = _fetch_json(f"https://hacker-news.firebaseio.com/v0/item/{sid}.json")
        if not story or story.get("type") != "story":
            continue
        score = story.get("score", 0)
        if score < 50:
            continue

        title = story.get("title", "")
        link = story.get("url", f"https://news.ycombinator.com/item?id={sid}")

        # 尝试抓正文
        content = f"[HN Score: {score}, Comments: {story.get('descendants', 0)}]"
        if link and "ycombinator" not in link:
            raw = _fetch_url(link)
            if raw:
                content = _clean_html(raw)[:5000]

        items.append({
            "title": title, "link": link, "author": story.get("by", ""),
            "content": content, "published": "",
        })

    conn = db.get_db()
    n = _save_items(conn, source["id"], items)
    conn.close()
    print(f"  → 新增 {n} 条")
    return n


# ============================================================
#  手动内容源（markdown 文件）
# ============================================================
def collect_manual(source):
    """从本地 markdown 文件采集手动整理的内容"""
    cfg = json.loads(source["fetch_config"]) if source["fetch_config"] else {}
    file_path = cfg.get("file", "")
    if not file_path:
        print(f"  [MANUAL] {source['name']} — 无文件配置")
        return 0

    from pathlib import Path
    p = Path(file_path)
    if not p.exists():
        print(f"  [MANUAL] {source['name']} — 文件不存在: {file_path}")
        return 0

    print(f"  [MANUAL] {source['name']} ← {file_path}")
    content = p.read_text(encoding="utf-8")

    # 按 --- 分割多条内容
    sections = re.split(r'\n---+\n', content)
    items = []
    for section in sections:
        section = section.strip()
        if len(section) < 50:
            continue
        # 第一行作为标题
        lines = section.split("\n")
        title = lines[0].strip("# ").strip()[:100]
        body = "\n".join(lines[1:]).strip() if len(lines) > 1 else section
        items.append({
            "title": title, "link": "", "author": source["name"],
            "content": body, "published": "",
        })

    conn = db.get_db()
    n = _save_items(conn, source["id"], items)
    conn.close()
    print(f"  → 新增 {n} 条")
    return n


# ============================================================
#  主入口
# ============================================================
def collect_all():
    conn = db.get_db()
    sources = db.get_active_sources(conn)
    conn.close()

    total = 0
    for src in sources:
        method = src["fetch_method"]
        cfg = json.loads(src["fetch_config"]) if src["fetch_config"] else {}
        try:
            if method == "rss":
                n = collect_rss(src)
            elif method == "rsshub":
                n = collect_rsshub(src)
            elif method == "scrape":
                if "xueqiu" in (src["platform"] or ""):
                    n = collect_rsshub(src)  # 雪球走 RSSHub
                elif "paulgraham" in (src["platform"] or ""):
                    n = collect_paul_graham(src)
                else:
                    n = collect_manual(src)
            elif method == "api":
                if "hackernews" in (src["platform"] or ""):
                    n = collect_hackernews(src)
                else:
                    n = 0
            elif method == "manual":
                n = collect_manual(src)
            else:
                n = 0
        except Exception as e:
            print(f"  [ERR] {src['name']}: {e}")
            n = 0

        if n > 0:
            conn = db.get_db()
            db.update_source_fetched(conn, src["id"])
            conn.close()

        total += n
        time.sleep(0.3)

    print(f"\n采集完成: 共新增 {total} 条内容")
    return total


if __name__ == "__main__":
    collect_all()
