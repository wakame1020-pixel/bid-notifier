"""
官公需情報ポータルサイト（kkj.go.jp）の検索APIを使って
「内装」関連の入札案件（国・都道府県・市区町村）の新着をチェックし、
一覧ページ用のデータファイル（bids_data.json）を更新するスクリプト。

GitHub Actions で定期実行される想定。
"""

import os
import json
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta

import requests

API_URL = "https://www.kkj.go.jp/api/"
SEEN_FILE = os.path.join(os.path.dirname(__file__), "seen_ids.json")
DATA_FILE = os.path.join(os.path.dirname(__file__), "bids_data.json")

# 一覧に残しておく日数（これより古い公告日の案件は一覧から自動的に削除）
KEEP_DAYS = 60

# ---- 検索条件（ここを編集して調整してください） ----
# OR条件でまとめて検索するキーワード
KEYWORDS = ["内装", "内装工事", "内装改修", "内装仕上", "建具工事"]
QUERY = " OR ".join(KEYWORDS)

# カテゴリー: 1=物品, 2=工事, 3=役務
# 「内装工事」と「内装修繕役務」の両方を取得し、それぞれにラベルを付けて区別する
CATEGORIES = [
    {"code": 2, "label": "内装工事"},
    {"code": 3, "label": "内装修繕役務"},
]

# 何日前の公告日以降を対象にするか（APIへの負荷軽減・重複取得防止のため）
LOOKBACK_DAYS = 5

# 取得件数上限（APIの仕様上、最大1000）
COUNT = 1000


def fetch_bids(category_code, category_label):
    since = (datetime.now().date() - timedelta(days=LOOKBACK_DAYS)).isoformat()
    params = {
        "Query": QUERY,
        "Count": COUNT,
        "CFT_Issue_Date": f"{since}/",
        "Category": category_code,
    }

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
        data["_categoryLabel"] = category_label
        results.append(data)
    return results


def fetch_all_bids():
    all_results = []
    for c in CATEGORIES:
        items = fetch_bids(c["code"], c["label"])
        print(f"  [{c['label']}] 取得件数: {len(items)}")
        all_results.extend(items)
    return all_results


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


def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, encoding="utf-8") as f:
            return json.load(f)
    return []


def save_data(records):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)


def to_record(b):
    return {
        "key": b.get("Key"),
        "projectName": b.get("ProjectName") or "(件名不明)",
        "orgName": b.get("OrganizationName") or "不明",
        "prefecture": b.get("PrefectureName") or "その他",
        "city": b.get("CityName") or "",
        "issueDate": b.get("CftIssueDate") or "",
        "deadline": b.get("TenderSubmissionDeadline") or "",
        "url": b.get("ExternalDocumentURI") or "",
        "category": b.get("_categoryLabel") or "その他",
    }


def main():
    seen = load_seen()
    bids = fetch_all_bids()
    print(f"取得件数(合計): {len(bids)}")

    new_items = [b for b in bids if b.get("Key") and b["Key"] not in seen]
    for b in new_items:
        seen.add(b["Key"])

    # 一覧ページ用データ：新着分を追加し、古い案件は削除して保存
    data = load_data()
    existing_keys = {r["key"] for r in data}
    added = 0
    for b in new_items:
        if b.get("Key") not in existing_keys:
            data.append(to_record(b))
            added += 1

    cutoff = (datetime.now().date() - timedelta(days=KEEP_DAYS)).isoformat()
    data = [r for r in data if not r.get("issueDate") or r["issueDate"] >= cutoff]
    data.sort(key=lambda r: r.get("issueDate", ""), reverse=True)
    save_data(data)
    save_seen(seen)

    print(f"新規追加: {added} 件 / 一覧データ合計: {len(data)} 件")


if __name__ == "__main__":
    main()
