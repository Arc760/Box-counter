"""Supabase 数据库操作，隔离 DB 逻辑。"""
from __future__ import annotations

import streamlit as st
import pandas as pd
from supabase import create_client, Client

COLUMNS = [
    "round_id",
    "box1_pet", "box1_family", "box1_egg",
    "box2_pet", "box2_family", "box2_egg",
    "box3_pet", "box3_family", "box3_egg",
    "round_egg_group",
    "note",
]


@st.cache_resource
def get_client(service: bool = False) -> Client:
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_SERVICE_KEY"] if service else st.secrets["SUPABASE_ANON_KEY"]
    return create_client(url, key)


def load_df(user_uuid: str) -> pd.DataFrame:
    """加载指定用户的全部记录。"""
    client = get_client()
    res = (
        client.table("boxes")
        .select("*")
        .eq("user_uuid", user_uuid)
        .order("round_id")
        .execute()
    )
    if not res.data:
        return pd.DataFrame(columns=COLUMNS + ["id"])
    df = pd.DataFrame(res.data)
    for c in COLUMNS:
        if c not in df.columns:
            df[c] = ""
    return df[COLUMNS + ["id"]].fillna("")


def save_row(user_uuid: str, row: dict) -> None:
    """保存/更新一条记录（同一用户同 round_id 则覆盖）。"""
    client = get_client()
    payload = {"user_uuid": user_uuid, **row}
    client.table("boxes").upsert(
        payload,
        on_conflict="user_uuid,round_id"
    ).execute()


def delete_row(user_uuid: str, row_id: int) -> None:
    """删除指定记录（双重校验 user_uuid，防止误删他人数据）。"""
    client = get_client()
    client.table("boxes").delete().eq("id", row_id).eq("user_uuid", user_uuid).execute()


def load_all_df() -> pd.DataFrame:
    """管理员专用：使用 service_role key 绕过 RLS，读取全部用户数据。"""
    client = get_client(service=True)
    res = client.table("boxes").select("*").order("created_at").execute()
    if not res.data:
        return pd.DataFrame(columns=["user_uuid"] + COLUMNS)
    return pd.DataFrame(res.data).fillna("")