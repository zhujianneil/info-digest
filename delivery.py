"""信息精选系统 - 推送层 (飞书 app + tenant_access_token)

2026-06-27 嵌入 investment-monitor 容器修正:
  - 容器用飞书 app (FEISHU_APP_ID + FEISHU_APP_SECRET),不是 webhook
  - 凭证在 /app/.env (跟 investment-monitor 一致)
  - 走 im/v1/messages,receive_id_type=chat_id
  - target chat: env FEISHU_CHAT_ID,默认 FEISHU_HOME_CHANNEL
"""
import json
import time
import os
import requests
import config


_token_cache = {"token": None, "expires": 0}


def _get_tenant_token():
    """获取飞书 tenant_access_token (带缓存)"""
    now = time.time()
    if _token_cache["token"] and _token_cache["expires"] > now:
        return _token_cache["token"]

    app_id = config.get_feishu_app_id()
    secret = config.get_feishu_secret()
    if not app_id or not secret:
        print("[ERR] FEISHU_APP_ID / FEISHU_APP_SECRET not set")
        return None

    resp = requests.post(
        f"{config.FEISHU_API_BASE}/auth/v3/tenant_access_token/internal",
        json={"app_id": app_id, "app_secret": secret},
        timeout=10,
    )
    data = resp.json()
    if data.get("code") != 0:
        print(f"[ERR] token failed: {data}")
        return None

    token = data["tenant_access_token"]
    _token_cache["token"] = token
    _token_cache["expires"] = now + data.get("expire", 7200) - 60
    return token


def _resolve_chat_id():
    """优先 FEISHU_CHAT_ID,fallback FEISHU_HOME_CHANNEL (investment-monitor 风格)"""
    return config.get_feishu_chat_id()


def send_text(text, chat_id=None):
    """发送文本消息到飞书群"""
    token = _get_tenant_token()
    if not token:
        return False

    chat_id = chat_id or _resolve_chat_id()
    if not chat_id:
        print("[ERR] no FEISHU_CHAT_ID / FEISHU_HOME_CHANNEL")
        return False

    resp = requests.post(
        f"{config.FEISHU_API_BASE}/im/v1/messages?receive_id_type=chat_id",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        json={
            "receive_id": chat_id,
            "msg_type": "text",
            "content": json.dumps({"text": text}, ensure_ascii=False),
        },
        timeout=10,
    )
    data = resp.json()
    if data.get("code") != 0:
        print(f"[ERR] send failed: {data}")
        return False
    print(f"飞书消息发送成功 (msg_id: {data.get('data', {}).get('message_id', '?')})")
    return True


def send_rich_text(title, content_lines, chat_id=None):
    """发送富文本消息 (post 类型) 到飞书群"""
    token = _get_tenant_token()
    if not token:
        return False

    chat_id = chat_id or _resolve_chat_id()
    if not chat_id:
        print("[ERR] no FEISHU_CHAT_ID / FEISHU_HOME_CHANNEL")
        return False

    post_content = {"zh_cn": {"title": title, "content": content_lines}}

    resp = requests.post(
        f"{config.FEISHU_API_BASE}/im/v1/messages?receive_id_type=chat_id",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        json={
            "receive_id": chat_id,
            "msg_type": "post",
            "content": json.dumps(post_content, ensure_ascii=False),
        },
        timeout=10,
    )
    data = resp.json()
    if data.get("code") != 0:
        print(f"[ERR] rich send failed: {data}")
        return False
    print(f"飞书富文本发送成功")
    return True


def send_digest(digest):
    """发送 Digest (走原版 markdown → post 富文本)"""
    if not digest:
        return False

    title = digest["title"]
    body = digest["body"]

    # 把 markdown body 解析成飞书 post 格式
    lines = body.split("\n")
    content_lines = []
    current_para = []

    for line in lines:
        if line.startswith("---"):
            if current_para:
                content_lines.append(current_para)
                current_para = []
            content_lines.append([{"tag": "hr"}])
        elif line.startswith("**") and line.endswith("**"):
            if current_para:
                content_lines.append(current_para)
                current_para = []
            text = line.strip("*")
            current_para.append({"tag": "text", "text": text, "style": ["bold"]})
        elif line.strip() == "":
            if current_para:
                content_lines.append(current_para)
                current_para = []
        else:
            text = line.strip()
            if text.startswith("📎 "):
                url = text[2:].strip()
                # 飞书富文本 <a> href 不允许空格;file:// 路径含空格时降级为纯文本
                if " " in url or "\n" in url or not (url.startswith("http://") or url.startswith("https://") or url.startswith("file://")):
                    current_para.append({"tag": "text", "text": text})
                else:
                    current_para.append({"tag": "a", "text": "📎 原文链接", "href": url})
            elif text.startswith("🔑 "):
                current_para.append({"tag": "text", "text": text[2:], "style": ["italic"]})
            elif text.startswith("💡 "):
                current_para.append({"tag": "text", "text": text})
            elif text.startswith("• "):
                current_para.append({"tag": "text", "text": "  " + text})
            else:
                current_para.append({"tag": "text", "text": text})

    if current_para:
        content_lines.append(current_para)

    content_lines = [p for p in content_lines if p]

    if not content_lines:
        return send_text(body)

    return send_rich_text(title, content_lines)


if __name__ == "__main__":
    ok = send_text("🧪 info-digest 推送测试 (走飞书 app, 看到请忽略)")
    print(f"Result: {'OK' if ok else 'FAILED'}")
