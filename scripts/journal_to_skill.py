#!/usr/bin/env python3
"""journal_to_skill.py — 将AI/安全情报转化为蒙多学习技能"""

import json
import re
import sys
from datetime import datetime
from pathlib import Path

JOURNAL_CACHE = Path(__file__).parent.parent / "journal_cache"
SKILLS_OUTPUT = Path(__file__).parent.parent / "skills" / "learning"
MAX_SUMMARY_LENGTH = 300

# 领域标签映射
DOMAIN_TAGS = {
    "ai": ["AI", "机器学习", "人工智能"],
    "security": ["网络安全", "信息安全", "安全研究"],
}

# 关键发现识别词（英文 + 中文）
FINDING_KEYWORDS = [
    # 通用
    'find', 'show', 'demonstrate', 'reveal', 'discover', 'propose',
    'develop', 'achieve', 'improve', 'novel', 'new', 'result',
    '突破', '发现', '提出', '开发', '实现', '改进', '创新',
    # 安全
    'vulnerability', 'exploit', 'attack', 'CVE', 'zero-day', 'patch',
    'ransomware', 'malware', 'breach', 'APT', 'bypass', 'disclosure',
    '漏洞', '攻击', '勒索', '恶意', '补丁', '入侵', '绕过',
    # AI
    'model', 'training', 'transformer', 'LLM', 'GPT', 'fine-tune',
    'benchmark', 'state-of-the-art', 'SOTA', 'performance',
    '模型', '训练', '推理', '大模型', '性能', '参数',
]


def sanitize_filename(title):
    """清洗标题为安全文件名"""
    title = re.sub(r'<!\[CDATA\[(.*?)\]\]>', r'\1', title, flags=re.DOTALL)
    title = re.sub(r'&lt;', '<', title)
    title = re.sub(r'&gt;', '>', title)
    title = re.sub(r'&amp;', '&', title)
    title = re.sub(r'&quot;', '"', title)
    title = re.sub(r'&#39;', "'", title)
    safe = re.sub(r'[^\w\s一-鿿-]', '', title)
    safe = re.sub(r'[\s]+', '-', safe.strip())
    return safe[:60].rstrip('-')


def generate_skill_name(article):
    """生成技能名称"""
    source = article.get('source', 'unknown').lower()
    source = re.sub(r'[^a-z]', '-', source).strip('-')
    title_words = article['title'].lower().split()[:3]
    title_slug = '-'.join(
        re.sub(r'[^a-z0-9一-鿿]', '', w)
        for w in title_words if w
    )
    date_str = datetime.now().strftime('%Y%m%d')
    return f"learn-{source}-{title_slug}-{date_str}"


def extract_key_findings(summary):
    """提取关键技术发现"""
    if not summary:
        return []
    sentences = re.split(r'[.。!！?？\n]', summary)
    findings = []
    for s in sentences:
        s = s.strip()
        if len(s) < 25:
            continue
        if any(kw in s.lower() for kw in FINDING_KEYWORDS):
            findings.append(s)
    return findings[:5]


def clean_text(text):
    """清洗文本中的XML/HTML杂质"""
    if not text:
        return ''
    text = re.sub(r'<!\[CDATA\[(.*?)\]\]>', r'\1', text, flags=re.DOTALL)
    for entity, char in [
        ('&lt;', '<'), ('&gt;', '>'), ('&amp;', '&'),
        ('&quot;', '"'), ('&#39;', "'"), ('&#x27;', "'"),
    ]:
        text = text.replace(entity, char)
    text = ' '.join(text.split())
    return text.strip()


def generate_skill_content(article):
    """生成完整的技能Markdown"""
    skill_name = generate_skill_name(article)
    date_str = datetime.now().strftime('%Y-%m-%d')
    clean_title = clean_text(article['title'])
    key_findings = extract_key_findings(article.get('summary', ''))
    domain = article.get('domain', 'tech')
    category = article.get('category', 'general')

    # 生成标签
    tags = [domain, category]
    if domain in DOMAIN_TAGS:
        tags.extend(DOMAIN_TAGS[domain])

    frontmatter = f"""---
name: {skill_name}
description: >
  [{domain.upper()}] {article.get('source', 'Unknown')} — {clean_title[:80]}
  蒙多AI+安全每日学习系统自动提取。
version: 1.0.0
author: mundo-learning-bot
priority: MEDIUM
auto_activate: MANUAL
category: learning
domain: {domain}
source: {article.get('source', 'unknown')}
published: {article.get('published', 'unknown')}
learned: {date_str}
tags: {tags}
---"""

    body = f"""
# {clean_title}

**来源**: [{article.get('source', 'Unknown')}]({article['link']})
**领域**: {domain.upper()}
**分类**: {category}
**学习日期**: {date_str}

---

## 内容摘要

{clean_text(article.get('summary', '暂无摘要'))}

## 关键技术点

"""

    if key_findings:
        for i, finding in enumerate(key_findings, 1):
            body += f"{i}. {finding}\n"
    else:
        body += "待人工分析补充...\n"

    body += f"""
## 蒙多战术笔记

> 🎯 **领域**: {domain.upper()}
> 💡 **要点**: {clean_title[:60]}...
> 🔗 **原文**: {article['link']}
>
> 此知识已纳入蒙多AI+安全知识库，随时可调用。

---

*由蒙多AI+安全每日学习系统自动生成*
"""
    return skill_name, frontmatter + body


def process_articles(articles_file=None):
    """处理文章缓存并生成技能文件"""
    if articles_file:
        input_path = Path(articles_file)
    else:
        article_files = sorted(JOURNAL_CACHE.glob("articles_*.json"), reverse=True)
        if not article_files:
            print("没有找到待处理的文章缓存")
            return 0
        input_path = article_files[0]

    with open(input_path, 'r', encoding='utf-8') as f:
        articles = json.load(f)

    if not articles:
        print("文章列表为空")
        return 0

    SKILLS_OUTPUT.mkdir(parents=True, exist_ok=True)
    created_count = 0

    for article in articles:
        try:
            skill_name, content = generate_skill_content(article)
            skill_file = SKILLS_OUTPUT / f"{skill_name}.md"

            if skill_file.exists():
                print(f"  跳过（已存在）: {skill_name}")
                continue

            with open(skill_file, 'w', encoding='utf-8') as f:
                f.write(content)

            print(f"  创建: {skill_name}")
            created_count += 1

        except Exception as e:
            print(f"  失败 [{article.get('title', '?')[:40]}]: {e}")

    print(f"\n共创建 {created_count} 个新技能")
    return created_count


def generate_daily_digest(articles_file=None):
    """生成每日学习摘要"""
    if articles_file:
        input_path = Path(articles_file)
    else:
        article_files = sorted(JOURNAL_CACHE.glob("articles_*.json"), reverse=True)
        if not article_files:
            return None
        input_path = article_files[0]

    with open(input_path, 'r', encoding='utf-8') as f:
        articles = json.load(f)

    if not articles:
        return None

    date_str = datetime.now().strftime('%Y%m%d')
    display_date = datetime.now().strftime('%Y-%m-%d')
    skill_name = f"learn-daily-digest-{date_str}"

    # 统计
    ai_count = sum(1 for a in articles if a.get('domain') == 'ai')
    sec_count = sum(1 for a in articles if a.get('domain') == 'security')

    frontmatter = f"""---
name: {skill_name}
description: >
  蒙多每日AI+安全学习摘要：{datetime.now().strftime('%Y年%m月%d日')}
  包含{len(articles)}条AI前沿与网络安全情报。
  其中AI {ai_count}条，安全 {sec_count}条。
version: 1.0.0
author: mundo-learning-bot
priority: HIGH
auto_activate: MANUAL
category: learning
---"""

    body = f"""
# 蒙多每日AI+安全摘要 — {display_date}

今日共捕获 **{len(articles)}** 条情报（🤖 AI: {ai_count} | 🔒 安全: {sec_count}）

---

## 情报列表

"""

    # 按领域+来源分组
    by_domain = {}
    for article in articles:
        domain = article.get('domain', '其他')
        if domain not in by_domain:
            by_domain[domain] = {}
        source = article.get('source', 'Unknown')
        if source not in by_domain[domain]:
            by_domain[domain][source] = []
        by_domain[domain][source].append(article)

    domain_icons = {'ai': '🤖', 'security': '🔒'}

    for domain, sources in by_domain.items():
        icon = domain_icons.get(domain, '📌')
        body += f"\n### {icon} {domain.upper()}\n\n"
        for source, items in sources.items():
            body += f"#### {source}\n\n"
            for i, article in enumerate(items, 1):
                body += f"{i}. **{clean_text(article['title'])}**\n"
                if article.get('summary'):
                    s = clean_text(article['summary'])[:200]
                    body += f"   > {s}{'...' if len(article.get('summary', '')) > 200 else ''}\n"
                body += f"   [阅读原文]({article['link']})\n\n"

    body += f"""
---

## 蒙多战报

> 📡 今日扫描 **{len(by_domain)}** 个领域、**{len(articles)}** 条情报。
> 🤖 AI 阵地: {ai_count} 条前沿动态
> 🔒 安全阵地: {sec_count} 条威胁情报
> 全部纳入了蒙多AI+安全知识库。

---

*由蒙多AI+安全每日学习系统自动生成*
"""

    skill_file = SKILLS_OUTPUT / f"{skill_name}.md"
    with open(skill_file, 'w', encoding='utf-8') as f:
        f.write(frontmatter + body)

    print(f"生成每日摘要: {skill_name}")
    return skill_name


if __name__ == '__main__':
    articles_file = sys.argv[1] if len(sys.argv) > 1 else None

    print("=== 蒙多AI+安全学习系统 ===\n")
    print("处理情报...")
    count = process_articles(articles_file)

    print("\n生成每日摘要...")
    digest = generate_daily_digest(articles_file)

    print(f"\n完成！创建 {count} 个学习技能 + 1 个每日摘要")
