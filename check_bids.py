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
from email.header import Header

import requests

API_URL = "https://www.kkj.go.jp/api/"
SEEN_FILE = os.path.join(os.path.dirname(__file__), "seen_ids.json")

KEYWORDS = ["内装", "内装工事", "内装改修", "内装仕上", "建具工事"]
QUERY = " OR ".join(KEYWORDS)

CATEGORY = 2  # 工事
LOOKBACK_DAYS = 5
COUNT = 1000

def _debug_info(label, value):
    if value is None:
        print(f"{label}: None (未設定)")
        return
    weird = [(i, f"U+{ord(c):04X}") for i, c in enumerate(value) if ord(c) < 0x21 or ord(c) > 0x7E]
    print(f"{label}: 長さ={len(value)} 通常のASCII以外の文字={weird}")


def _clean_env(value):
    if value is None:
        return value
    return value.strip().replace("\u00a0", "").replace("\u200b", "")


SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587
SMTP_USER = _clean_env(os.environ.get("SMTP_USER"))
SMTP_PASSWORD = _clean_env(os.environ.get("SMTP_PASSWORD"))

_notify_to_raw = _clean_env(os.environ.get("NOTIFY_TO")) or SMTP_USER
NOTIFY_TO_LIST = [addr.strip() for addr in _notify_to_raw.split(",") if addr.strip()]


def fetch_bids():
    since =
