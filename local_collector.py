"""信息精选系统 - 本地采集 (知识库 git pull + 扫描 + inbox)

支持：
  - knowledge-bases/ 目录: git pull 同步 + 递归扫描所有 .md
  - inbox/ 目录: 丢文件进去 (md/txt/pdf/docx/html/json/org)
  - 处理完移到 processed/

2026-06-27 嵌入 investment-monitor 改造:
  - 知识库路径通过环境变量 INFO_DIGEST_KB_ROOT 配置,默认 ./knowledge-bases
  - 每个知识库目录首次使用时自动 git pull (需要 ~/.git-credentials)
  - 知识库 vs inbox 用不同 source_name,方便过滤
"""
import os
import re
import json
import hashlib
import shutil
import subprocess
from datetime import datetime, timezone, timedelta
from pathlib import Path
import db
import config

# CST 时区用于"今/昨"判定 (知识库是长内容,不靠 fetched_at)
CST = timezone(timedelta(hours=8))

INBOX_DIR = config.PROJECT_DIR / "inbox"
PROCESSED_DIR = config.PROJECT_DIR / "processed"

# 知识库根目录:环境变量优先,默认 ./knowledge-bases
KB_ROOT = Path(os.environ.get("INFO_DIGEST_KB_ROOT", str(config.PROJECT_DIR / "knowledge-bases")))

SUPPORTED_EXT = {'.md', '.txt', '.pdf', '.docx', '.html', '.htm', '.json', '.org'}

# 排除的目录 (Obsidian 索引 / git 内部)
EXCLUDE_DIRS = {'.git', '.obsidian', 'processed', 'inbox', '.trash', 'attachments'}

# 确保目录存在
INBOX_DIR.mkdir(exist_ok=True)
PROCESSED_DIR.mkdir(exist_ok=True)


# ============================================================
#  工具函数
# ============================================================

def _git_pull(repo_dir: Path) -> bool:
    """对单个知识库仓库 git pull. 依赖 ~/.git-credentials (credential.helper=store)"""
    if not (repo_dir / ".git").exists():
        return False
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_dir), "pull", "--ff-only"],
            capture_output=True, text=True, timeout=60,
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
        )
        if result.returncode == 0:
            print(f"    [git pull OK] {repo_dir.name}: {result.stdout.strip()[:120]}")
            return True
        else:
            print(f"    [git pull ERR] {repo_dir.name}: {result.stderr.strip()[:200]}")
            return False
    except subprocess.TimeoutExpired:
        print(f"    [git pull TIMEOUT] {repo_dir.name}")
        return False
    except Exception as e:
        print(f"    [git pull ERR] {repo_dir.name}: {e}")
        return False


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
            import pymupdf
            doc = pymupdf.open(str(filepath))
            text = ''
            for page in doc:
                text += page.get_text()
            doc.close()
            return text
        except ImportError:
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
            return f"[DOCX 文件，需要安装 python-docx]"

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
        sections = re.split(r'\n(?=## )', text)
    else:
        sections = [text]

    items = []
    for section in sections:
        section = section.strip()
        if len(section) < 30:
            continue
        lines = section.split('\n')
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


def _ensure_source(name: str, platform: str, fetch_method: str, fetch_config: str = "{}") -> int:
    """确保 source 存在,返回 id"""
    conn = db.get_db()
    row = conn.execute(f"SELECT id FROM {config.__dict__.get('TABLE_PREFIX', 'digest_')}sources WHERE name=?", (name,)).fetchone()
    if row:
        conn.close()
        return row[0]
    conn.execute(
        f"INSERT INTO {config.__dict__.get('TABLE_PREFIX', 'digest_')}sources (name, tier, type, platform, fetch_method, fetch_config) VALUES (?, 1, '本地', ?, ?, ?)",
        (name, platform, fetch_method, fetch_config),
    )
    conn.commit()
    new_id = conn.execute(f"SELECT id FROM {config.__dict__.get('TABLE_PREFIX', 'digest_')}sources WHERE name=?", (name,)).fetchone()[0]
    conn.close()
    return new_id


def _ingest_file(filepath: Path, source_id: int, source_name: str, source_label: str = "knowledge") -> int:
    """把单个文件入库 (按 --- 或 ## 拆条). source_label 用于标记 url 区别"""
    try:
        text = _extract_text(filepath)
        if not text or len(text) < 30:
            return 0
        sections = _parse_sections(text)
        count = 0
        conn = db.get_db()
        for section in sections:
            ext_id = hashlib.md5(
                (str(filepath) + section['title']).encode()
            ).hexdigest()[:16]
            # 用 file:// + label 区分,知识库和 inbox 的 url scheme 一致但带 source name
            url = f"file://{source_label}/{filepath}"
            ok = db.upsert_content(
                conn, source_id, ext_id,
                title=section['title'],
                url=url,
                author=source_name,
                content=section['content'][:8000],
                content_type='text',
                published_at=datetime.fromtimestamp(filepath.stat().st_mtime, tz=CST).isoformat(),
                word_count=len(section['content']),
            )
            if ok:
                count += 1
        conn.close()
        return count
    except Exception as e:
        print(f"    [ERR ingest] {filepath.name}: {e}")
        return 0


# ============================================================
#  知识库扫描 (git pull + 递归 ingest)
# ============================================================

def collect_knowledge_bases():
    """扫 KB_ROOT 下所有 git repo,git pull + 递归 ingest 所有 md 文件"""
    if not KB_ROOT.exists():
        print(f"  [KB] KB_ROOT 不存在: {KB_ROOT}")
        return 0

    # 找直接子目录 (一个 repo 一个子目录)
    repos = [d for d in KB_ROOT.iterdir() if d.is_dir() and (d / ".git").exists()]
    if not repos:
        # 也支持单层 md 直接放 KB_ROOT
        repos = [KB_ROOT]

    total = 0
    for repo in repos:
        repo_name = repo.name
        print(f"  [KB] 仓库: {repo_name}")

        # git pull
        if (repo / ".git").exists():
            _git_pull(repo)

        # 创建/取 source id
        source_id = _ensure_source(
            name=f"知识库:{repo_name}",
            platform="local",
            fetch_method="local",
            fetch_config=json.dumps({"root": str(repo)}),
        )

        # 递归扫 md
        md_files = [
            f for f in repo.rglob("*.md")
            if not any(ex in f.parts for ex in EXCLUDE_DIRS)
        ]
        print(f"    → {len(md_files)} 个 md 文件")
        for i, md in enumerate(md_files):
            if i % 20 == 0:
                print(f"    ... 进度 {i}/{len(md_files)}", flush=True)
            n = _ingest_file(md, source_id, f"知识库:{repo_name}", source_label="kb")
            total += n

    print(f"  [KB] 知识库采集完成: 新增 {total} 条")
    return total


# ============================================================
#  Inbox 扫描 (丢文件)
# ============================================================

def collect_inbox():
    """扫描 inbox/ 目录,采集新文件"""
    files = [f for f in INBOX_DIR.iterdir()
             if f.is_file() and f.suffix.lower() in SUPPORTED_EXT]

    if not files:
        return 0

    source_id = _ensure_source(
        name="inbox",
        platform="local",
        fetch_method="local",
    )

    print(f"  [INBOX] 扫描到 {len(files)} 个文件")
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
                    url=f"file://inbox/{filepath}",
                    author=filepath.stem,
                    content=section['content'][:8000],
                    content_type='text',
                    published_at=datetime.fromtimestamp(filepath.stat().st_mtime, tz=CST).isoformat(),
                    word_count=len(section['content']),
                )
                if new_id:
                    count += 1

            if count > 0:
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
    print(f"  [INBOX] 采集完成: 新增 {total} 条")
    return total


# ============================================================
#  主入口
# ============================================================

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "kb":
        collect_knowledge_bases()
    elif len(sys.argv) > 1 and sys.argv[1] == "inbox":
        collect_inbox()
    else:
        n = collect_knowledge_bases()
        m = collect_inbox()
        print(f"\n总计: KB {n} 条 + Inbox {m} 条")
