"""Supabase 数据库操作 — 用 requests 直接调用 REST API，兼容所有 Python 版本。"""
from __future__ import annotations

import streamlit as st
import pandas as pd
import requests

COLUMNS = [
    "round_id",
    "box1_pet", "box1_family", "box1_egg",
    "box2_pet", "box2_family", "box2_egg",
    "box3_pet", "box3_family", "box3_egg",
    "round_egg_group",
    "note",
]


def _headers(service: bool = False) -> dict:
    key = st.secrets["SUPABASE_SERVICE_KEY"] if service else st.secrets["SUPABASE_ANON_KEY"]
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }


def _url(table: str, path: str = "") -> str:
    base = st.secrets["SUPABASE_URL"].rstrip("/")
    return f"{base}/rest/v1/{table}{path}"


# ── 昵称 ──────────────────────────────────────────────────────────

def get_nickname(user_uuid: str) -> str:
    """读取用户昵称，不存在返回空字符串。"""
    r = requests.get(
        _url("user_profiles"),
        headers=_headers(),
        params={"user_uuid": f"eq.{user_uuid}", "select": "nickname"},
        timeout=10,
    )
    r.raise_for_status()
    data = r.json()
    if data:
        return data[0].get("nickname", "")
    return ""


def nickname_exists(nickname: str) -> bool:
    """检查昵称是否已被其他人使用。"""
    r = requests.get(
        _url("user_profiles"),
        headers=_headers(service=True),
        params={"nickname": f"eq.{nickname.strip()}", "select": "user_uuid"},
        timeout=10,
    )
    r.raise_for_status()
    return len(r.json()) > 0


def save_nickname(user_uuid: str, nickname: str) -> bool:
    """保存/更新用户昵称。昵称重复返回 False，成功返回 True。"""
    # 检查是否已被其他人用了
    r = requests.get(
        _url("user_profiles"),
        headers=_headers(service=True),
        params={"nickname": f"eq.{nickname.strip()}", "select": "user_uuid"},
        timeout=10,
    )
    r.raise_for_status()
    existing = r.json()
    if existing and existing[0]["user_uuid"] != user_uuid:
        return False  # 昵称被别人占用

    headers = {**_headers(), "Prefer": "resolution=merge-duplicates,return=minimal"}
    r = requests.post(
        _url("user_profiles"),
        headers=headers,
        json={"user_uuid": user_uuid, "nickname": nickname.strip()},
        timeout=10,
    )
    r.raise_for_status()
    return True


def load_all_nicknames() -> dict[str, str]:
    """管理员用：返回 {user_uuid: nickname} 字典。"""
    r = requests.get(
        _url("user_profiles"),
        headers=_headers(service=True),
        params={"select": "user_uuid,nickname"},
        timeout=10,
    )
    r.raise_for_status()
    return {row["user_uuid"]: row["nickname"] for row in r.json()}


# ── 数据记录 ──────────────────────────────────────────────────────

def load_df(user_uuid: str) -> pd.DataFrame:
    """加载指定用户的全部记录。"""
    r = requests.get(
        _url("boxes"),
        headers=_headers(),
        params={
            "user_uuid": f"eq.{user_uuid}",
            "order": "round_id.asc",
            "select": "*",
        },
        timeout=10,
    )
    r.raise_for_status()
    data = r.json()
    if not data:
        return pd.DataFrame(columns=COLUMNS + ["id"])
    df = pd.DataFrame(data)
    for c in COLUMNS:
        if c not in df.columns:
            df[c] = ""
    return df[COLUMNS + ["id"]].fillna("")


def save_row(user_uuid: str, row: dict) -> None:
    """保存/更新一条记录（同一用户同 round_id 则覆盖）。"""
    payload = {"user_uuid": user_uuid, **row}
    headers = {**_headers(), "Prefer": "resolution=merge-duplicates,return=minimal"}
    r = requests.post(_url("boxes"), headers=headers, json=payload, timeout=10)
    r.raise_for_status()


def delete_row(user_uuid: str, row_id: int) -> None:
    """删除指定记录。"""
    r = requests.delete(
        _url("boxes"),
        headers=_headers(),
        params={
            "id": f"eq.{row_id}",
            "user_uuid": f"eq.{user_uuid}",
        },
        timeout=10,
    )
    r.raise_for_status()


def load_all_df() -> pd.DataFrame:
    """管理员专用：service_role key 读取全部用户数据。"""
    r = requests.get(
        _url("boxes"),
        headers=_headers(service=True),
        params={"order": "created_at.asc", "select": "*"},
        timeout=10,
    )
    r.raise_for_status()
    data = r.json()
    if not data:
        return pd.DataFrame(columns=["user_uuid"] + COLUMNS)
    return pd.DataFrame(data).fillna("")