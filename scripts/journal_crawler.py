#!/usr/bin/env python3
"""蒙多AI+安全每日学习 — 多源情报抓取引擎

来源：
  AI 前沿：
    - arXiv cs.AI (RSS 2.0, 人工智能)
    - arXiv cs.CR (RSS 2.0, 密码学与安全)
    - Hugging Face Daily Papers
    - Anthropic Research Blog (Atom)
    - OpenAI Blog (RSS)
  网络安全：
    - The Hacker News (RSS)
    - Krebs on Security (RSS)
    - Google Project Zero Blog (Atom)
    - CISA Alerts (RSS)

冗余度: 最多 2 篇/源/天，总 ~20 篇/天
"""

import json
import hashlib
import re
import sys
import io
from datetime import datetime, timedelta
from pathlib import Path

# ─── Windows 编码修复 ───
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

try:
    from scrapling.fetchers import Fetcher
    USE_SCRAPLING = True
except ImportError:
    USE_SCRAPLING = False

import xml.etree.ElementTree as ET

# ──────────── 情报源配置 ────────────
FEEDS = {
    # ── AI 学术前沿 ──
    "arxiv_cs_ai": {
        "name": "arXiv cs.AI",
        "url": "https://rss.arxiv.org/rss/cs.AI",
        "domain": "ai",
        "category": "research",
    },
    "arxiv_cs_cr": {
        "name": "arXiv cs.CR (密码学与安全)",
        "url": "https://rss.arxiv.org/rss/cs.CR",
        "domain": "security",
        "category": "research",
    },
    # ── AI 产品/工程 ──
    "anthropic_research": {
        "name": "Anthropic Research",
        "url": "https://raw.githubusercontent.com/Olshansk/rss-feeds/refs/heads/main/feeds/feed_anthropic_research.xml",
        "domain": "ai",
        "category": "industry",
    },
    "huggingface_blog": {
        "name": "Hugging Face Blog",
        "url": "https://huggingface.co/blog/feed.xml",
        "domain": "ai",
        "category": "engineering",
    },
    "openai_blog": {
        "name": "OpenAI Blog",
        "url": "https://openai.com/news/rss.xml",
        "domain": "ai",
        "category": "industry",
    },
    # ── 安全新闻 ──
    "the_hacker_news": {
        "name": "The Hacker News",
        "url": "https://feeds.feedburner.com/TheHackersNews",
        "domain": "security",
        "category": "news",
    },
    "krebs": {
        "name": "Krebs on Security",
        "url": "https://krebsonsecurity.com/feed/",
        "domain": "security",
        "category": "investigation",
    },
    "project_zero": {
        "name": "Google Project Zero",
        "url": "https://googleprojectzero.blogspot.com/feeds/posts/default?alt=rss",
        "domain": "security",
        "category": "vulnerability-research",
    },
}

OUTPUT_DIR = Path(__file__).parent.parent / "journal_cache"
DEDUP_FILE = OUTPUT_DIR / "seen_articles.json"


def load_seen():
    if DEDUP_FILE.exists():
        with open(DEDUP_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}


def save_seen(data):
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(DEDUP_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def article_hash(title, link):
    return hashlib.sha256(f"{title}:{link}".encode()).hexdigest()[:16]


def _to_str(data) -> str:
    """将 Scrapling bytes/str 统一为 str"""
    if data is None:
        return ""
    if isinstance(data, bytes):
        return data.decode('utf-8', errors='replace')
    return str(data)


def fetch(url, timeout=30) -> str:
    """抓取 URL，返回字符串内容"""
    if USE_SCRAPLING:
        try:
            page = Fetcher.get(url, timeout=timeout)
            return _to_str(getattr(page, 'body', page) or page)
        except Exception as e:
            print(f"  [warn] Scrapling: {e}")

    try:
        import requests as req
        resp = req.get(url, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }, timeout=timeout)
        resp.raise_for_status()
        return resp.text or ""
    except Exception as e:
        print(f"  [warn] requests: {e}")
        return ""


def clean_cdata(text):
    if not text:
        return ''
    for entity, char in [('&lt;', '<'), ('&gt;', '>'), ('&amp;', '&'),
                          ('&quot;', '"'), ('&#39;', "'")]:
        text = text.replace(entity, char)
    text = re.sub(r'<!\[CDATA\[(.*?)\]\]>', r'\1', text, flags=re.DOTALL)
    return ' '.join(text.split()).strip()


def parse_atom(xml_text: str) -> list:
    """解析 Atom feed"""
    articles = []
    try:
        root = ET.fromstring(xml_text)
        ns = {'a': 'http://www.w3.org/2005/Atom'}
        for entry in root.findall('.//a:entry', ns):
            title = entry.find('a:title', ns)
            link = entry.find('a:link', ns)
            summary = entry.find('a:summary', ns)
            published = entry.find('a:published', ns) or entry.find('a:updated', ns)

            link_href = ''
            if link is not None:
                link_href = link.get('href', '') or (link.text or '').strip()

            articles.append({
                'title': clean_cdata(title.text) if title is not None else '',
                'link': link_href,
                'summary': clean_cdata(summary.text)[:800] if summary is not None else '',
                'published': (published.text or '').strip() if published is not None else ''
            })
    except ET.ParseError:
        pass
    return articles


def parse_rss2(xml_text: str) -> list:
    """解析 RSS 2.0 feed"""
    articles = []
    try:
        root = ET.fromstring(xml_text)
        for item in root.iter('item'):
            title = item.find('title')
            link = item.find('link')
            desc = item.find('description')
            pub = item.find('pubDate')

            link_text = ''
            if link is not None:
                link_text = (link.text or '').strip()
            # Some feeds use <link>URL</link>, others <link/>
            if not link_text:
                # Fallback regex extract
                for child in item:
                    if child.tag == 'link' and child.text:
                        link_text = child.text.strip()
                        break

            articles.append({
                'title': clean_cdata(title.text) if title is not None else '',
                'link': link_text,
                'summary': clean_cdata(desc.text)[:800] if desc is not None else '',
                'published': (pub.text or '').strip() if pub is not None else ''
            })
    except ET.ParseError:
        pass
    return articles


def parse_xml(xml_text: str) -> list:
    """自动识别 XML 格式并解析"""
    if not xml_text:
        return []

    # Atom?
    if 'xmlns="http://www.w3.org/2005/Atom"' in xml_text[:2000] or \
       '<feed ' in xml_text[:500]:
        articles = parse_atom(xml_text)
        if articles:
            return articles

    # RSS 2.0 / RDF
    articles = parse_rss2(xml_text)
    if articles:
        return articles

    # ── 最坏情况: 正则暴力提取 ──
    return _regex_extract(xml_text)


def _regex_extract(xml_text: str) -> list:
    """正则暴力提取（处理任何畸形 XML）"""
    articles = []
    titles = re.findall(r'<title[^>]*>([^<]+)</title>', xml_text)
    links = re.findall(
        r'(?:<link[^>]*>(https?://[^<]+)</link>'
        r'|<link[^>]*href="(https?://[^"]+)"[^>]*>)',
        xml_text
    )
    descs = re.findall(r'<description[^>]*>([^<]+)</description>', xml_text)
    pub_dates = re.findall(r'<pubDate[^>]*>([^<]+)</pubDate>', xml_text)

    # Flatten tuple links from alternation
    flat_links = []
    for l in links:
        if isinstance(l, tuple):
            flat_links.append(l[0] or l[1])
        else:
            flat_links.append(l)

    # Skip first title (channel/feed title)
    start = 1
    for i, title in enumerate(titles[start:start + 20], start=start):
        idx = i - start
        link = flat_links[idx] if idx < len(flat_links) else ''
        desc = descs[idx] if idx < len(descs) else ''
        pub = pub_dates[idx] if idx < len(pub_dates) else ''

        if not title or len(title) < 5:
            continue

        articles.append({
            'title': clean_cdata(title),
            'link': link,
            'summary': clean_cdata(desc)[:800],
            'published': pub.strip()
        })

    return articles


def crawl_feed(key, info, seen, max_n=2):
    """抓单个情报源"""
    domain_emoji = "🤖" if info['domain'] == 'ai' else "🔒"
    print(f"  {domain_emoji} {info['name']}...", end=' ')

    xml = fetch(info['url'])
    if not xml:
        print("(无响应)")
        return []

    articles = parse_xml(xml)
    if not articles:
        print(f"(解析失败: {len(xml)} bytes)")
        return []

    new_articles = []
    for art in articles:
        if not art['title'] or len(art['title']) < 5:
            continue
        if not art['link'] and not key.startswith('arxiv'):
            continue

        h = article_hash(art['title'], art['link'])
        if h in seen:
            continue

        art['source'] = info['name']
        art['domain'] = info['domain']
        art['category'] = info['category']
        art['hash'] = h
        art['crawled_at'] = datetime.now().isoformat()

        new_articles.append(art)
        seen[h] = {
            'title': art['title'],
            'crawled_at': art['crawled_at']
        }

        if len(new_articles) >= max_n:
            break

    print(f"({len(new_articles)} 新)")
    return new_articles


def crawl_all(max_per_source=2):
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    seen = load_seen()

    print(f"[{datetime.now():%Y-%m-%d %H:%M}] 蒙多 AI+安全 情报扫描启动\n")

    all_articles = []
    for key, info in FEEDS.items():
        try:
            arts = crawl_feed(key, info, seen, max_per_source)
            all_articles.extend(arts)
        except Exception as e:
            print(f"    ⨯ ERROR: {e}")

    # 清理30天前记录
    cutoff = (datetime.now() - timedelta(days=30)).isoformat()
    seen = {k: v for k, v in seen.items() if v.get('crawled_at', '') > cutoff}
    save_seen(seen)

    # 汇总
    ai_n = sum(1 for a in all_articles if a['domain'] == 'ai')
    sec_n = sum(1 for a in all_articles if a['domain'] == 'security')

    print(f"\n{'=' * 50}")
    print(f"扫描完成: {len(all_articles)} 条新情报 (🤖 AI: {ai_n} | 🔒 安全: {sec_n})")

    # 保存缓存
    if all_articles:
        fname = OUTPUT_DIR / f"articles_{datetime.now().strftime('%Y%m%d')}.json"
        with open(fname, 'w', encoding='utf-8') as f:
            json.dump(all_articles, f, ensure_ascii=False, indent=2)
        print(f"缓存已保存: {fname}")

    return all_articles


if __name__ == '__main__':
    max_per = int(sys.argv[1]) if len(sys.argv) > 1 else 2
    articles = crawl_all(max_per)

    # 输出 JSON 供下游（修复 UnicodeEncodeError）
    result = json.dumps({'total': len(articles)}, ensure_ascii=False)
    try:
        print(result)
    except UnicodeEncodeError:
        print(result.encode('utf-8', errors='replace').decode('utf-8', errors='replace'))
