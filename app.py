"""惊喜盒子蛋组池假设检验 — 多用户版，数据存 Supabase。"""

from __future__ import annotations

import json
import math
import re
import uuid as _uuid
from collections import Counter
from pathlib import Path

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
from streamlit_js_eval import streamlit_js_eval

from db import (
    COLUMNS,
    delete_row,
    load_all_df,
    load_df,
    save_row,
)

st.set_page_config(page_title="惊喜盒子 · 蛋组检验", layout="wide")

ROOT = Path(__file__).resolve().parent
PETS_FILE = ROOT / "pets.txt"
PET_IMG_MAP_FILE = ROOT / "pet_images.json"
PET_DIRS = [ROOT / "s2", ROOT / "s1", ROOT]
S2_DIR = ROOT / "s2"
FAM_DIR = ROOT / "Types"
EXTS = (".png", ".jpg", ".jpeg", ".webp")

OTHER_PET_LABEL = "其他宠物"
EXTRA_LIST_PETS = frozenset({"星尘虫", "果冻"})

EGG_GROUPS = [
    "动物组", "植物组", "妖精组", "天空组", "拟人组",
    "妖精组", "巨灵组", "昆虫组", "机械组",
]
OLD_BALL_KEYS = {
    "anxing", "bianhuan", "buguang", "gaoji", "guanghe", "haozhan",
    "jueyuan", "king", "kuanghuan", "lengjing", "meimiao", "qiqv",
    "taosha", "tiaowen", "wangdou",
}

FAMILY_CN_TO_IMG = {
    "火系": "fire", "水系": "water", "冰系": "ice", "电系": "electric",
    "草系": "grass", "虫系": "bug", "幽系": "ghost", "恶系": "devil",
    "机械系": "tech", "幻系": "magic", "龙系": "dragon", "翼系": "fly",
    "武系": "fight", "地系": "ground", "毒系": "poison", "光系": "light",
    "萌系": "cute", "普通系": "normal", "普通": "normal",
}

# ── UUID（浏览器本地存储） ────────────────────────────────────────


def get_or_create_uuid() -> str | None:
    """
    从 localStorage 读取 UUID；不存在则生成并写入。
    因为 streamlit_js_eval 是异步的，第一次渲染可能返回 None，
    调用方应在 None 时 st.stop() 等待下一次 rerun。
    """
    stored = streamlit_js_eval(
        js_expressions="localStorage.getItem('rokworld_uuid')",
        key="read_uuid",
    )
    if stored and str(stored).strip() not in ("", "None", "null"):
        return str(stored).strip()

    # 还没有：生成一个并写入
    new_id = str(_uuid.uuid4())
    streamlit_js_eval(
        js_expressions=f"localStorage.setItem('rokworld_uuid', '{new_id}'); '{new_id}'",
        key="write_uuid",
    )
    return None   # 等下一次 rerun


# ── 宠物元数据 ───────────────────────────────────────────────────


def normalize_egg(raw: str) -> str:
    s = str(raw).strip()
    if not s or s.lower() == "nan":
        return ""
    return s


def is_legacy_ball_egg(value: str) -> bool:
    return normalize_egg(value) in OLD_BALL_KEYS


def pet_images_mtime() -> int:
    return int(PET_IMG_MAP_FILE.stat().st_mtime_ns) if PET_IMG_MAP_FILE.exists() else 0


@st.cache_data
def load_pet_meta(file_mtime: int) -> dict[str, dict[str, str]]:
    if not PET_IMG_MAP_FILE.exists():
        return {}
    raw = json.loads(PET_IMG_MAP_FILE.read_text(encoding="utf-8"))
    out: dict[str, dict[str, str]] = {}
    for name, val in raw.items():
        key = str(name).strip()
        if isinstance(val, str):
            out[key] = {"img": val.strip(), "family": ""}
        else:
            out[key] = {
                "img": str(val.get("img", "")).strip(),
                "family": str(val.get("family", "")).strip(),
            }
    return out


def family_candidates() -> list[str]:
    return sorted({f for f in FAMILY_CN_TO_IMG.keys() if f}, key=len, reverse=True)


def family_from_attrs(attrs: str) -> str:
    text = str(attrs or "").strip()
    if not text:
        return ""
    for family in family_candidates():
        if family in text:
            return family
    return ""


def pet_family(pet_name: str) -> str:
    n = str(pet_name).strip()
    if not n:
        return ""
    meta = load_pet_meta(pet_images_mtime())
    fam = meta.get(n, {}).get("family", "").strip()
    if fam:
        return fam
    return family_from_attrs(pet_attrs(n))


def pet_img_key(name: str) -> str:
    n = str(name).strip()
    if not n:
        return ""
    meta = load_pet_meta(pet_images_mtime())
    if n in meta and meta[n].get("img"):
        return meta[n]["img"]
    return Path(n).stem


@st.cache_data
def s2_image_keys() -> frozenset[str]:
    if not S2_DIR.exists():
        return frozenset()
    return frozenset(p.stem for p in S2_DIR.glob("*.png"))


def parse_pet_line(line: str) -> tuple[str, str, str]:
    s = line.strip()
    if not s or s.startswith("#"):
        return "", "", ""
    for sep in (",", "，", "\t"):
        if sep in s:
            name, tail = s.split(sep, 1)
            name = name.strip()
            tail = tail.strip()
            if not tail:
                return name, "", ""
            parts = [p.strip() for p in re.split(r"[，,\t]", tail) if p.strip()]
            egg = parts[0] if parts else ""
            attrs = " ".join(parts[1:]) if len(parts) > 1 else ""
            return name, egg, attrs
    return s, "", ""


def pet_catalog_mtime() -> int:
    return int(PETS_FILE.stat().st_mtime_ns) if PETS_FILE.exists() else 0


@st.cache_data
def load_pet_catalog(file_mtime: int) -> dict[str, dict[str, str]]:
    catalog: dict[str, dict[str, str]] = {}
    if not PETS_FILE.exists():
        return catalog
    for line in PETS_FILE.read_text(encoding="utf-8").splitlines():
        name, egg, attrs = parse_pet_line(line)
        if name:
            catalog[name] = {"egg": egg, "attrs": attrs}
    return catalog


def pet_egg_group(pet_name: str) -> str:
    return load_pet_catalog(pet_catalog_mtime()).get(str(pet_name).strip(), {}).get("egg", "")


def pet_attrs(pet_name: str) -> str:
    return load_pet_catalog(pet_catalog_mtime()).get(str(pet_name).strip(), {}).get("attrs", "")


def pet_matches_family(pet_name: str, family_filter: str) -> bool:
    if not family_filter or family_filter == "全部系别":
        return True
    family = pet_family(pet_name)
    if family == family_filter:
        return True
    return family_filter in pet_attrs(pet_name)


def family_filter_options() -> list[str]:
    return ["全部系别"] + sorted({f for f in FAMILY_CN_TO_IMG.keys() if f})


def in_selectable_list(pet_name: str) -> bool:
    n = str(pet_name).strip()
    if not n or n == OTHER_PET_LABEL:
        return False
    return True


def pet_selection_counts(df: pd.DataFrame) -> Counter[str]:
    counts: Counter[str] = Counter()
    for i in (1, 2, 3):
        col = f"box{i}_pet"
        if col not in df.columns:
            continue
        counts.update(
            str(pet).strip()
            for pet in df[col].astype(str)
            if str(pet).strip()
        )
    return counts


@st.cache_data
def load_selectable_pets(
    rank: tuple[tuple[str, int], ...] | None = None,
    file_mtime: int = 0,
) -> list[str]:
    rank_dict = dict(rank) if rank is not None else {}
    catalog = load_pet_catalog(file_mtime)
    return sorted(
        (n for n in catalog if in_selectable_list(n)),
        key=lambda x: (-rank_dict.get(x, 0), len(x), x),
    )


def family_img_key(family: str) -> str:
    f = str(family).strip()
    if f in FAMILY_CN_TO_IMG:
        return FAMILY_CN_TO_IMG[f]
    return f


def read_pets_file() -> str:
    if not PETS_FILE.exists():
        return (
            "# 格式：宠物中文名,蛋组[,属性...]\n"
            "影狸,\n果冻,\n星尘虫,\n"
        )
    return PETS_FILE.read_text(encoding="utf-8")


def save_pets_file(content: str) -> None:
    PETS_FILE.write_text(content, encoding="utf-8")
    load_pet_catalog.clear()
    load_selectable_pets.clear()


def pick_pet(widget_key: str, selectable: list[str]) -> tuple[str, bool, str, str]:
    st.markdown("**宠物**")
    family_filter = st.selectbox(
        "按系别筛选",
        family_filter_options(),
        key=f"{widget_key}_family_filter",
        label_visibility="collapsed",
    )
    filtered = (
        [p for p in selectable if pet_matches_family(p, family_filter)]
        if family_filter != "全部系别"
        else selectable
    )
    opts = ["—"] + filtered + [OTHER_PET_LABEL]
    choice = st.selectbox(
        "选择宠物",
        opts,
        key=f"{widget_key}_sel",
        format_func=lambda x: {"—": "（不填）", OTHER_PET_LABEL: OTHER_PET_LABEL}.get(x, x),
        label_visibility="collapsed",
    )
    if choice == "—":
        return "", False, "", ""
    if choice == OTHER_PET_LABEL:
        st.caption("其他宠物：不记录名称与蛋组，保存为空白选项。")
        return "", True, "", ""
    fam = pet_family(choice)
    egg = pet_egg_group(choice)
    if fam:
        st.markdown(f"**系别：** {fam}")
    else:
        st.caption("系别：未配置（pet_images.json）")
    if egg:
        st.markdown(f"**蛋组：** {egg}")
    else:
        st.caption("蛋组：未配置（pets.txt 写为「名字,蛋组」）")
    return choice, False, fam, egg


def collect_box_entry(i: int) -> dict:
    sel = st.session_state.get(f"box{i}_sel", "—")
    if sel == "—":
        return {"pet": "", "fam": "", "egg": "", "is_other": False}
    if sel == OTHER_PET_LABEL:
        return {"pet": "", "fam": "", "egg": "", "is_other": True}
    pet = str(sel).strip()
    return {"pet": pet, "fam": pet_family(pet), "egg": pet_egg_group(pet), "is_other": False}


def round_entries_ready(entries: list[dict]) -> bool:
    if len(entries) != 3:
        return False
    return all(e["is_other"] or (e["pet"] and e["egg"]) for e in entries)


def reset_round_inputs() -> None:
    st.session_state["round_reset_pending"] = True


def apply_round_input_reset() -> None:
    if not st.session_state.get("round_reset_pending"):
        return
    for i in (1, 2, 3):
        st.session_state[f"box{i}_sel"] = "—"
        st.session_state[f"box{i}_family_filter"] = "全部系别"
    st.session_state["round_note"] = ""
    st.session_state["round_egg_group"] = ""
    st.session_state["round_reset_pending"] = False


def bind_enter_to_save(ready: bool) -> None:
    if not ready:
        return
    components.html(
        """
        <script>
        (function () {
          const doc = window.parent.document;
          if (doc.body.dataset.enterSaveBound === "1") return;
          doc.body.dataset.enterSaveBound = "1";
          doc.addEventListener("keydown", function (e) {
            if (e.key !== "Enter" || e.isComposing) return;
            const t = e.target;
            if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA")) return;
            const btn = Array.from(doc.querySelectorAll("button")).find(
              (b) => b.innerText && b.innerText.includes("保存本轮")
            );
            if (btn) { e.preventDefault(); btn.click(); }
          });
        })();
        </script>
        """,
        height=0,
    )


def img_path(dirpath: Path, key: str) -> Path | None:
    if not key:
        return None
    name = Path(str(key).strip()).stem
    for ext in EXTS:
        p = dirpath / f"{name}{ext}"
        if p.exists():
            return p
    return None


def pet_img(name: str) -> Path | None:
    if not name:
        return None
    file_key = pet_img_key(name)
    for d in PET_DIRS:
        for ext in EXTS:
            p = d / f"{file_key}{ext}"
            if p.exists():
                return p
    return None


def round_eggs(row: pd.Series) -> list[str]:
    return [normalize_egg(row[f"box{i}_egg"]) for i in (1, 2, 3)]


def chi2_uniform(counts: Counter) -> tuple[float, int]:
    n = sum(counts.values())
    k = len(counts)
    if n == 0 or k < 2:
        return 0.0, 0
    exp = n / k
    chi2 = sum((c - exp) ** 2 / exp for c in counts.values())
    return chi2, k - 1


def binom_p_same_three(p_hit: float, n: int, k: int) -> float:
    if k <= 0:
        return 1.0
    total = 0.0
    for i in range(k, n + 1):
        total += math.comb(n, i) * (p_hit**i) * ((1 - p_hit) ** (n - i))
    return total


def analyze(df: pd.DataFrame, eggs: list[str]) -> dict:
    n_rounds = len(df)
    n_slots = n_rounds * 3
    all_eggs: list[str] = []
    same3 = same2plus = all_diff = 0
    per_round_unique: Counter = Counter()

    for _, row in df.iterrows():
        egs = [e for e in round_eggs(row) if e]
        all_eggs.extend(egs)
        u = len(set(egs))
        per_round_unique[u] += 1
        if u == 1 and len(egs) == 3:
            same3 += 1
        elif u == 3:
            all_diff += 1
        if u <= 2 and len(egs) == 3:
            same2plus += 1

    slot_counts = Counter(all_eggs)
    k = len(eggs) or max(len(slot_counts), 1)
    p_all_same_null = 1 / (k**2) if k else 0
    p_all_same_obs = same3 / n_rounds if n_rounds else 0
    chi2, df_chi = chi2_uniform(slot_counts)

    return {
        "n_rounds": n_rounds,
        "n_slots": n_slots,
        "slot_counts": slot_counts,
        "same3": same3,
        "same2plus": same2plus,
        "all_diff": all_diff,
        "per_round_unique": per_round_unique,
        "p_all_same_null": p_all_same_null,
        "p_all_same_obs": p_all_same_obs,
        "chi2": chi2,
        "chi2_df": df_chi,
        "k_eggs": k,
    }


def render_stats(df: pd.DataFrame, eggs: list[str]) -> None:
    """渲染蛋组分析面板（供普通用户和管理员复用）。"""
    if len(df) == 0:
        st.info("还没有数据。")
        return

    stats = analyze(df, eggs)
    n = stats["n_rounds"]
    k = stats["k_eggs"]

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("记录轮数", n)
    m2.metric("总格子数", stats["n_slots"])
    m3.metric("三轮蛋组全相同", stats["same3"], f"{100*stats['same3']/n:.1f}%" if n else "—")
    m4.metric("三轮蛋组全不同", stats["all_diff"], f"{100*stats['all_diff']/n:.1f}%" if n else "—")

    st.subheader("假设对照")
    st.markdown(
        f"""
| 假设 | 含义 | 三轮同蛋组概率（理论） | 你的观测 |
|------|------|------------------------|----------|
| **A. 独立随机** | 每格从 {k} 个蛋组独立抽取 | **{100*stats['p_all_same_null']:.2f}%** | **{100*stats['p_all_same_obs']:.1f}%** ({stats['same3']}/{n} 轮) |
| **B. 固定蛋组池** | 每轮三只必为同一蛋组 | **100%** | **{100*stats['p_all_same_obs']:.1f}%** |
| **C. 弱相关** | 有蛋组倾向但不锁死 | 介于 A 与 B 之间 | 见下方分布 |
        """
    )

    if n >= 5:
        p_null = stats["p_all_same_null"]
        p_obs = binom_p_same_three(p_null, n, stats["same3"])
        st.caption(
            f"在假设 A 下，出现 ≥{stats['same3']} 轮「三轮同蛋组」的近似概率 ≈ {p_obs:.4f}"
        )

    st.subheader("每轮蛋组种类数")
    u = stats["per_round_unique"]
    uc1, uc2 = st.columns(2)
    with uc1:
        st.write("**1 种（三只相同）**", u.get(1, 0), "轮")
        st.write("**2 种**", u.get(2, 0), "轮")
    with uc2:
        st.write("**3 种（全不同）**", u.get(3, 0), "轮")
        st.write("**≥2 种有重复**", stats["same2plus"], "轮")

    st.subheader("各蛋组出现次数")
    slot_df = (
        pd.DataFrame([{"蛋组": e, "次数": c} for e, c in stats["slot_counts"].most_common()])
        if stats["slot_counts"]
        else pd.DataFrame(columns=["蛋组", "次数"])
    )
    if len(slot_df):
        slot_df["占比%"] = (slot_df["次数"] / stats["n_slots"] * 100).round(1)
        slot_df["理论均匀%"] = round(100 / k, 1)
        slot_df["偏差"] = (slot_df["占比%"] - slot_df["理论均匀%"]).round(1)
        st.dataframe(slot_df, use_container_width=True, hide_index=True)
        st.bar_chart(slot_df.set_index("蛋组")["次数"])
        chi2, df_chi = stats["chi2"], stats["chi2_df"]
        if df_chi > 0:
            st.caption(
                f"均匀性卡方统计量 χ²={chi2:.2f}（df={df_chi}）。"
                "χ² 越大说明越不像「各蛋组机会均等」。"
            )

    st.subheader("系别分布（辅助）")
    fam_cols = [f"box{i}_family" for i in (1, 2, 3)]
    available = [c for c in fam_cols if c in df.columns]
    if available:
        fams = df[available].astype(str).replace("", pd.NA).stack().dropna()
        if len(fams):
            st.bar_chart(fams.value_counts())


# ════════════════════════════════════════════════════════════════
#  主流程
# ════════════════════════════════════════════════════════════════

# 1. 获取用户 UUID
user_uuid = get_or_create_uuid()
if not user_uuid:
    st.info("正在初始化，请稍候…")
    st.stop()

# 2. 加载该用户的数据
df = load_df(user_uuid)
eggs = EGG_GROUPS

selectable_pets = load_selectable_pets(
    tuple(sorted(pet_selection_counts(df).items())),
    file_mtime=pet_catalog_mtime(),
)

# 3. 侧边栏
with st.sidebar:
    st.header("宠物名单")
    st.caption(
        f"当前可选 {len(selectable_pets)} 只"
        f"（按历史点击次数优先）：{', '.join(selectable_pets[:10]) or '（请在 pets.txt 配置）'}{'…' if len(selectable_pets) > 10 else ''}"
    )
    with st.expander("编辑 pets.txt（名字,蛋组）"):
        edited = st.text_area(
            "每行：中文名,蛋组",
            value=read_pets_file(),
            height=320,
            key="pets_editor",
        )
        if st.button("保存 pets.txt"):
            save_pets_file(edited)
            st.success("已保存。")
            st.rerun()
    st.caption("`pet_images.json` 配置图片与系别；`pets.txt` 配置蛋组。")
    st.divider()
    st.caption(f"你的设备 ID（最后 8 位）：`...{user_uuid[-8:]}`")

# 4. 旧数据警告
legacy_cols = [c for c in df.columns if c.endswith("_egg")]
if len(df) and any(
    df[c].map(is_legacy_ball_egg).any()
    for c in legacy_cols
    if c in df.columns
):
    st.warning("检测到旧数据里用了精灵球名（如 anxing）当蛋组，已无效。请删除或重新录入。")

st.title("洛克王国：世界 · 惊喜盒子蛋组检验")
st.caption("目标：用实测数据判断是否存在「蛋组池」，或每轮三选一是否围绕同一蛋组出现。")

tab_log, tab_stats, tab_rows, tab_admin = st.tabs(
    ["录入一轮", "蛋组分析", "全部记录", "🔒 管理员"]
)

# ── 录入 ─────────────────────────────────────────────────────────
with tab_log:
    st.subheader("记录本轮三选一")
    st.markdown(
        "选 **s2 / 星尘虫 / 果冻** 时，**系别**与**蛋组**自动填入；"
        f"选 **{OTHER_PET_LABEL}** 时不记录名称与蛋组。"
        "三个选项都选好后，在**非输入框**处按 **Enter** 可保存并进入下一轮。"
    )

    next_id = int(df["round_id"].max()) + 1 if len(df) and pd.notna(df["round_id"].max()) else 1
    if "next_round_id_pending" in st.session_state:
        st.session_state["next_round_id"] = st.session_state.pop("next_round_id_pending")
    if "next_round_id" not in st.session_state:
        st.session_state["next_round_id"] = max(next_id, 1)
    if st.session_state["next_round_id"] < next_id:
        st.session_state["next_round_id"] = next_id
    if st.session_state["next_round_id"] < 1:
        st.session_state["next_round_id"] = 1

    apply_round_input_reset()

    st.number_input("轮次编号", min_value=1, step=1, key="next_round_id")
    note = st.text_input("备注（可选）", placeholder="例如：某地图、第 N 个盒子", key="round_note")
    egg_group_input = st.text_input(
        "正在刷取的宠物蛋组",
        placeholder="例如：精灵组 / 植物组, 精灵组",
        key="round_egg_group",
    )

    cols = st.columns(3)
    for i, col in enumerate(cols, start=1):
        with col:
            st.markdown(f"**选项 {i}**")
            pick_pet(f"box{i}", selectable_pets)

    entries = [collect_box_entry(i) for i in (1, 2, 3)]
    ready = round_entries_ready(entries)
    if ready:
        st.caption("三个选项已就绪，按 Enter 或点击下方按钮保存。")
    bind_enter_to_save(ready)

    save = st.button("保存本轮", type="primary", key="save_round_btn")

    if save:
        round_id = int(st.session_state["next_round_id"])
        entries = [collect_box_entry(i) for i in (1, 2, 3)]
        missing_egg = [
            e["pet"] for e in entries
            if e["pet"] and not e.get("is_other") and not e["egg"]
        ]
        if missing_egg:
            st.error(f"以下宠物未在 pets.txt 配置蛋组：{', '.join(missing_egg)}")
        elif not round_entries_ready(entries):
            st.error("请为三个选项都选择宠物并填写蛋组，或选择「其他宠物」作为空白项。")
        else:
            row = {
                "round_id": round_id,
                "round_egg_group": str(st.session_state.get("round_egg_group", "")).strip(),
                "note": st.session_state.get("round_note", ""),
            }
            for i, e in enumerate(entries, start=1):
                row[f"box{i}_egg"] = normalize_egg(e["egg"])
                row[f"box{i}_pet"] = e["pet"].strip()
                row[f"box{i}_family"] = e["fam"].strip() if not e.get("is_other") else ""
            save_row(user_uuid, row)
            df = load_df(user_uuid)
            load_selectable_pets.clear()
            st.session_state["next_round_id_pending"] = round_id + 1
            reset_round_inputs()
            st.success(f"已保存第 {round_id} 轮，已切换到第 {round_id + 1} 轮。")
            st.rerun()

# ── 分析 ─────────────────────────────────────────────────────────
with tab_stats:
    if len(df) == 0:
        st.info("还没有数据。请先在「录入一轮」里记录惊喜盒子结果。")
    else:
        render_stats(df, eggs)

# ── 记录列表 ─────────────────────────────────────────────────────
with tab_rows:
    if len(df) == 0:
        st.info("暂无记录。")
    else:
        st.caption(f"共 {len(df)} 轮")
        for idx, r in df.sort_values("round_id", ascending=False).iterrows():
            egs = round_eggs(r)
            unique = len(set(egs))
            tag = "同蛋组" if unique == 1 else ("全不同" if unique == 3 else "部分相同")
            st.divider()
            st.subheader(f"第 {int(r['round_id'])} 轮 · {tag}")
            if str(r.get("note", "")).strip():
                st.caption(r["note"])
            if str(r.get("round_egg_group", "")).strip():
                st.caption(f"正在刷取的宠物蛋组：{r['round_egg_group']}")

            cols = st.columns(3)
            for i, col in enumerate(cols, start=1):
                with col:
                    egg = normalize_egg(r[f"box{i}_egg"])
                    pet = str(r.get(f"box{i}_pet", "") or "")
                    fam = str(r.get(f"box{i}_family", "") or "")
                    st.markdown(f"**蛋组：** {egg or '—'}")
                    if is_legacy_ball_egg(egg):
                        st.caption("⚠ 这是精灵球名，请改为真实蛋组")
                    if pet:
                        st.markdown(f"**宠物：** {pet}")
                    p_img = pet_img(pet) if pet else None
                    if p_img:
                        st.image(str(p_img), use_container_width=True)
                    elif pet:
                        st.caption("（暂无对应图片）")
                    if fam:
                        st.markdown(f"**系别：** {fam}")
                    f_img = img_path(FAM_DIR, family_img_key(fam)) if fam else None
                    if f_img:
                        st.image(str(f_img), width=48)

            row_id = r.get("id")
            if row_id and st.button("删除此轮", key=f"del_{idx}"):
                delete_row(user_uuid, int(row_id))
                df = load_df(user_uuid)
                st.rerun()

# ── 管理员 ───────────────────────────────────────────────────────
with tab_admin:
    st.subheader("管理员面板")
    token = st.text_input("管理员密码", type="password", key="admin_token")
    admin_ok = token and token == st.secrets.get("ADMIN_TOKEN", "")

    if not admin_ok:
        st.warning("请输入管理员密码以查看全局统计。")
    else:
        st.success("已验证管理员身份。")
        all_df = load_all_df()

        c1, c2, c3 = st.columns(3)
        c1.metric("总用户数", all_df["user_uuid"].nunique() if len(all_df) else 0)
        c2.metric("总记录轮数", len(all_df))
        c3.metric("总格子数", len(all_df) * 3)

        if len(all_df) > 0:
            st.subheader("各用户数据量")
            user_counts = (
                all_df.groupby("user_uuid")
                .agg(轮数=("round_id", "count"))
                .reset_index()
            )
            user_counts["user_uuid_short"] = user_counts["user_uuid"].str[-8:]
            st.dataframe(
                user_counts[["user_uuid_short", "轮数"]].rename(
                    columns={"user_uuid_short": "用户ID（后8位）"}
                ),
                use_container_width=True,
                hide_index=True,
            )

            st.subheader("全局蛋组分析")
            render_stats(all_df, eggs)