"""
官公需情報ポータルサイト（kkj.go.jp）の検索APIを使って
「内装」関連の入札案件（国・都道府県・市区町村）の新着をチェックし、
新しく見つかった案件があればメールで通知するスクリプト。

GitHub Actions で定期実行される想定。
"""

import os
import json
import time
import smtplib
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from email.mime.text import MIMEText

import requests

API_URL = "https://www.kkj.go.jp/api/"
SEEN_FILE = os.path.join(os.path.dirname(__file__), "seen_ids.json")

# ---- 検索条件（ここを編集して調整してください） ----
# OR条件でまとめて検索するキーワード
KEYWORDS = ["内装", "内装工事", "内装改修", "内装仕上", "建具工事"]
QUERY = " OR ".join(KEYWORDS)

# カテゴリー: 1=物品, 2=工事, 3=役務 （複数条件が必要な場合は None にして後段のPython側で絞り込み）
CATEGORY = 2  # 工事

# 何日前の公告日以降を対象にするか（APIへの負荷軽減・重複取得防止のため）
LOOKBACK_DAYS = 5

# 取得件数上限（APIの仕様上、最大1000）
COUNT = 1000

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587
SMTP_USER = os.environ.get("SMTP_USER")          # 送信元Gmailアドレス
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD")  # Gmailアプリパスワード
NOTIFY_TO = os.environ.get("NOTIFY_TO", SMTP_USER)  # 通知を受け取るメールアドレス（未指定なら送信元と同じ）


def fetch_bids():
    since = (datetime.now().date() - timedelta(days=LOOKBACK_DAYS)).isoformat()
    params = {
        "Query": QUERY,
        "Count": COUNT,
        "CFT_Issue_Date": f"{since}/",
    }
    if CATEGORY is not None:
        params["Category"] = CATEGORY

    resp = requests.get(API_URL, params=params, timeout=30)
    resp.raise_for_status()

    root = ET.fromstring(resp.content)

    error = root.find("Error")
    if error is not None:
        raise RuntimeError(f"API error: {error.text}")

    results = []
    for item in root.findall(".//SearchResult"):
        data = {}
        for child in item:
            if child.tag == "Attachments":
                continue
            data[child.tag] = child.text
        results.append(data)
    return results


def load_seen():
    if os.path.exists(SEEN_FILE):
        with open(SEEN_FILE, encoding="utf-8") as f:
            return set(json.load(f))
    return set()


def save_seen(seen):
    # 無限に増え続けないよう、直近で見つかった分だけ残す（簡易的に最新5000件まで保持）
    trimmed = list(seen)[-5000:]
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(trimmed, f, ensure_ascii=False, indent=2)


def build_message(b):
    area = f"{b.get('PrefectureName', '')}{b.get('CityName', '')}".strip()
    lines = [
        "【入札情報 新着】",
        b.get("ProjectName", "(件名不明)"),
        f"発注機関: {b.get('OrganizationName', '不明')}",
    ]
    if area:
        lines.append(f"地域: {area}")
    if b.get("CftIssueDate"):
        lines.append(f"公告日: {b.get('CftIssueDate')}")
    if b.get("TenderSubmissionDeadline"):
        lines.append(f"入札締切: {b.get('TenderSubmissionDeadline')}")
    if b.get("ExternalDocumentURI"):
        lines.append(b["ExternalDocumentURI"])
    return "\n".join(lines)


def send_email(subject, text):
    if not SMTP_USER or not SMTP_PASSWORD:
        raise RuntimeError("SMTP_USER / SMTP_PASSWORD が設定されていません")

    msg = MIMEText(text, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = SMTP_USER
    msg["To"] = NOTIFY_TO

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
        server.starttls()
        server.login(SMTP_USER, SMTP_PASSWORD)
        server.sendmail(SMTP_USER, [NOTIFY_TO], msg.as_string())


def main():
    seen = load_seen()
    bids = fetch_bids()
    print(f"取得件数: {len(bids)}")

    new_items = [b for b in bids if b.get("Key") and b["Key"] not in seen]

    if not new_items:
        print("新着案件はありませんでした")
        save_seen(seen)  # LOOKBACK_DAYSの範囲でseenを更新しておく
        return

    for b in new_items:
        seen.add(b["Key"])
        msg = build_message(b)
        subject = f"【入札情報】{b.get('ProjectName', '新着案件')}"
        try:
            send_email(subject, msg)
            print("通知送信:", b.get("ProjectName"))
        except Exception as e:
            print("通知送信に失敗:", e)
        time.sleep(1)  # 連続送信の間隔をあける

    save_seen(seen)
    print(f"{len(new_items)} 件の新着案件を通知しました")


if __name__ == "__main__":
    main()
