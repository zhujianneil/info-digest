"""信息精选系统 - 本地文件采集
扫描 inbox/ 目录，自动处理新文件。
支持：.md .txt .pdf .docx .html .json
处理完移到 processed/"""
import os
import re
import json
import hashlib
import shutil
from datetime import datetime
from pathlib import Path
import db
import config

INBOX_DIR = config.PROJECT_DIR / "inbox"
PROCESSED_DIR = config.PROJECT_DIR / "processed"

# 确保目录存在
INBOX_DIR.mkdir(exist_ok=True)
PROCESSED_DIR.mkdir(exist_ok=True)

SUPPORTED_EXT = {'.md', '.txt', '.pdf', '.docx', '.html', '.htm', '.json', '.org'}


def _extract_text(filepath: Path) -> str:
    """从文件提取纯文本"""
    ext = filepath.suffix.lower()

    if ext in ('.md', '.txt', '.org'):
        return filepath.read_text(encoding='utf-8', errors='replace')

    if ext in ('.html', '.htm'):
        from bs4 import BeautifulSoup
        html = filepath.read_text(encoding='utf-8', errors='replace')
        soup = BeautifulSoup(html, 'lxml')
        for tag in soup(["script", "style"]):
            tag.decompose()
        return soup.get_text(separator='\n', strip=True)

    if ext == '.pdf':
        try:
            import pymupdf  # PyMuPDF
            doc = pymupdf.open(str(filepath))
            text = ''
            for page in doc:
                text += page.get_text()
            doc.close()
            return text
        except ImportError:
            # fallback: try pdfplumber
            try:
                import pdfplumber
                with pdfplumber.open(str(filepath)) as pdf:
                    return '\n'.join(p.extract_text() or '' for p in pdf.pages)
            except ImportError:
                return f"[PDF 文件，需要安装 pymupdf: pip install pymupdf]"

    if ext == '.docx':
        try:
            import docx
            doc = docx.Document(str(filepath))
            return '\n'.join(p.text for p in doc.paragraphs)
        except ImportError:
            return f"[DOCX 文件，需要安装 python-docx: pip install python-docx]"

    if ext == '.json':
        data = json.loads(filepath.read_text(encoding='utf-8'))
        return json.dumps(data, ensure_ascii=False, indent=2)

    return ''


def _parse_sections(text: str) -> list:
    """
    把文本解析为多条内容。
    规则：
    - 如果有 --- 分隔符，按分隔符拆分
    - 否则整篇作为一条
    - 每条的第一行非空行作为标题
    """
    if '---' in text:
        sections = re.split(r'\n-{3,}\n', text)
    elif '\n## ' in text:
        # 按二级标题拆分
        sections = re.split(r'\n(?=## )', text)
    else:
        sections = [text]

    items = []
    for section in sections:
        section = section.strip()
        if len(section) < 30:
            continue
        lines = section.split('\n')
        # 提取标题
        title = ''
        body_start = 0
        for i, line in enumerate(lines):
            stripped = line.strip().lstrip('#').strip()
            if stripped and len(stripped) > 3:
                title = stripped[:120]
                body_start = i + 1
                break
        if not title:
            title = section[:60].replace('\n', ' ')
        body = '\n'.join(lines[body_start:]).strip()
        if not body:
            body = section
        items.append({'title': title, 'content': body})
    return items


def collect_inbox(source_id=None):
    """扫描 inbox/ 目录，采集新文件"""
    files = [f for f in INBOX_DIR.iterdir()
             if f.is_file() and f.suffix.lower() in SUPPORTED_EXT]

    if not files:
        return 0

    # 如果没有指定 source_id，用"本地文件"源
    if source_id is None:
        conn = db.get_db()
        row = conn.execute("SELECT id FROM sources WHERE name='本地文件'").fetchone()
        if not row:
            conn.execute("""
                INSERT INTO sources (name, tier, type, platform, fetch_method, fetch_config)
                VALUES ('本地文件', 1, '本地', 'local', 'local', '{}')
            """)
            conn.commit()
            row = conn.execute("SELECT id FROM sources WHERE name='本地文件'").fetchone()
        source_id = row[0]
        conn.close()

    print(f"  [LOCAL] inbox/ 扫描到 {len(files)} 个文件")
    total = 0
    conn = db.get_db()

    for filepath in files:
        print(f"    → {filepath.name}", end=" ", flush=True)
        try:
            text = _extract_text(filepath)
            if not text or len(text) < 30:
                print("(空/太短)")
                continue

            sections = _parse_sections(text)
            count = 0
            for section in sections:
                ext_id = hashlib.md5(
                    (filepath.name + section['title']).encode()
                ).hexdigest()[:16]

                new_id = db.upsert_content(
                    conn, source_id, ext_id,
                    title=section['title'],
                    url=f"file://{filepath}",
                    author=filepath.stem,
                    content=section['content'][:8000],
                    content_type='text',
                    published_at=datetime.fromtimestamp(filepath.stat().st_mtime).isoformat(),
                    word_count=len(section['content']),
                )
                if new_id:
                    count += 1

            if count > 0:
                # 移到 processed/
                dest = PROCESSED_DIR / filepath.name
                if dest.exists():
                    dest = PROCESSED_DIR / f"{filepath.stem}_{datetime.now().strftime('%H%M%S')}{filepath.suffix}"
                shutil.move(str(filepath), str(dest))
                print(f"✓ ({count}条) → processed/")
                total += count
            else:
                print("(已存在)")

        except Exception as e:
            print(f"✗ {e}")

    conn.close()
    print(f"  本地采集完成: {total} 条")
    return total


if __name__ == "__main__":
    collect_inbox()
