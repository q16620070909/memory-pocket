"""
记忆口袋 v4.0
图片 | 文字 | 语音 | 多图分析 | 每日总结 | 关联记忆 | 任务清单
"""

import os, shutil, tempfile
from datetime import datetime
from pathlib import Path

import streamlit as st

from analyzer import (
    analyze_image, analyze_text, analyze_batch,
    transcribe_audio, find_relationships, generate_daily_summary, generate_summary,
    load_user_tags, save_user_tags
)
from storage import (
    save_memory, save_text_memory, get_all_memories, get_memories_by_type,
    get_statistics, get_pending_tasks, get_completed_tasks, get_today_memories,
    get_recent_memories, get_memory_by_id,
    delete_memory, delete_memory_with_image, IMAGE_DIR, init_db,
    get_trips_grouped_by_location, mark_completed, mark_pending,
    update_tags, update_type, get_memories_by_tag, get_all_tags, get_schedules
)
from search import natural_search

st.set_page_config(page_title="记忆口袋", page_icon="🧠", layout="wide")

ICON_MAP = {"取件码":"📦","消费":"💰","灵感":"💡","聊天截图":"💬","出游照片":"🏔️","日程":"📅","文档":"📄","笔记":"📝","待办":"✅","其他":"📋"}

# ============================================================
# 侧边栏
# ============================================================
def render_sidebar():
    with st.sidebar:
        st.title("🧠 记忆口袋")
        stats = get_statistics()
        st.metric("总记忆", stats["总记忆数"])
        if stats["分类统计"]:
            for t, c in sorted(stats["分类统计"].items(), key=lambda x:x[1], reverse=True):
                st.text(f"{ICON_MAP.get(t, '📋')} {t}: {c}")
        st.divider()
        st.caption("v4.0 | 文字+语音+多图+关联")

# ============================================================
# Tab 1: 录入（图片 | 文字 | 语音）
# ============================================================
def tab_upload():
    st.header("📸 录入记忆")

    mode = st.radio("输入方式", ["📷 图片上传", "✏️ 文字输入", "🎤 语音输入"], horizontal=True)

    if mode == "📷 图片上传":
        _upload_images()
    elif mode == "✏️ 文字输入":
        _upload_text()
    else:
        _upload_voice()


def _upload_images():
    uploaded = st.file_uploader("拖拽或点击上传（支持多张）", type=["png","jpg","jpeg","webp"], accept_multiple_files=True)
    if not uploaded: return

    # 预览
    with st.expander(f"📷 已选 {len(uploaded)} 张", expanded=True):
        cols = st.columns(min(len(uploaded), 4))
        for i, f in enumerate(uploaded):
            with cols[i % 4]:
                st.image(f, use_container_width=True)

    batch_mode = len(uploaded) > 1
    btn_label = f"🚀 综合分析 {len(uploaded)} 张" if batch_mode else "🚀 开始分析"

    if st.button(btn_label, type="primary", use_container_width=True):
        if batch_mode:
            # 多图：先各自存，再批量分析
            paths = []
            for f in uploaded:
                filename = f"{datetime.now().strftime('%Y%m%d%H%M%S%f')}_{f.name}"
                dest = str(IMAGE_DIR / filename)
                with open(dest, "wb") as out:
                    out.write(f.getvalue())
                paths.append(dest)

            with st.spinner("综合分析中..."):
                batch_result = analyze_batch(paths)

            st.success(f"📊 {batch_result.get('组标题','未命名相册')}")
            st.markdown(f"**整体描述**: {batch_result.get('整体描述','')}")
            st.markdown(f"**标签**: {' '.join(batch_result.get('共同标签',[]))}")

            # 每张图也单独分析并存
            for i, p in enumerate(paths):
                r = analyze_image(p)
                mid = save_memory(p, r)
                info = batch_result.get("照片分析",[])
                if i < len(info):
                    r["一句话"] = info[i].get("场景","")
                save_memory(p, r)  # update with batch info
                st.caption(f"#{mid} {ICON_MAP.get(r.get('类型',''),'📋')} {generate_summary(r)}")
        else:
            # 单图
            f = uploaded[0]
            filename = f"{datetime.now().strftime('%Y%m%d%H%M%S%f')}_{f.name}"
            dest = str(IMAGE_DIR / filename)
            with open(dest, "wb") as out:
                out.write(f.getvalue())

            from analyzer import analyze_image_two_pass
            with st.spinner("AI 两轮分析中...（第1轮：识别类型 | 第2轮：精准提取）"):
                result = analyze_image_two_pass(dest)
            mid = save_memory(dest, result)
            st.success(f"#{mid} {ICON_MAP.get(result.get('类型',''),'📋')} {generate_summary(result)}")
            with st.expander("🔍 查看 AI 两轮分析过程"):
                two_pass = result.get("_两轮分析", {})
                if two_pass:
                    c1, c2 = st.columns(2)
                    with c1:
                        st.caption("🔎 第1轮：识别类型")
                        st.json(two_pass["第1轮"])
                    with c2:
                        st.caption("🎯 第2轮：精准提取")
                        st.json(two_pass["第2轮"])
                else:
                    st.json(result)


def _upload_text():
    text = st.text_area("写下任何东西——灵感、备忘、消费记录、待办事项...", height=150,
                        placeholder="比如：今天在京东买了本《深度学习》花了89块\n或者：下周五之前要交大创申报书\n或者：刚才想到一个做图像识别的idea...")
    if st.button("✏️ 记录", type="primary", use_container_width=True) and text.strip():
        with st.spinner("AI 分析中..."):
            result = analyze_text(text.strip())
        mid = save_text_memory(text.strip(), result)
        st.success(f"#{mid} {ICON_MAP.get(result.get('类型',''),'📋')} {generate_summary(result)}")
        with st.expander("详情"):
            st.json(result)


def _upload_voice():
    st.caption("点击麦克风按钮，开始说话（支持中文）")
    audio = st.audio_input("录音")
    if audio:
        st.audio(audio)
        with st.spinner("语音转文字中..."):
            transcript = transcribe_audio(audio.getvalue())
        if transcript and "失败" not in transcript:
            st.info(f"识别结果: {transcript}")
            with st.spinner("AI 分析中..."):
                result = analyze_text(transcript)
            mid = save_text_memory(transcript, result)
            st.success(f"#{mid} {ICON_MAP.get(result.get('类型',''),'📋')} {generate_summary(result)}")
        else:
            st.error(transcript or "语音识别失败，请用文字输入")


# ============================================================
# Tab 2: 浏览记忆
# ============================================================
def tab_browse():
    st.header("📋 浏览记忆")
    filter_type = st.selectbox("类型", ["全部","取件码","消费","灵感","聊天截图","出游照片","日程","文档","笔记","待办","其他"], key="browse_filter")
    memories = get_all_memories(100) if filter_type == "全部" else get_memories_by_type(filter_type)

    if not memories:
        st.info("还没有记忆")
        return

    # 点中某条记忆时显示详情
    if "selected_memory" not in st.session_state:
        st.session_state.selected_memory = None

    for m in memories:
        _render_card(m)

    # 详情弹窗
    if st.session_state.selected_memory:
        _show_detail(st.session_state.selected_memory)


def _render_card(m: dict):
    类型 = m.get("类型","其他")
    icon = ICON_MAP.get(类型,"📋")
    信息 = m.get("信息",{})
    标签 = m.get("标签",[])
    if isinstance(标签, str): 标签 = []
    time_str = (m.get("创建时间","") or "")[:16]
    img = m.get("图片路径","")

    with st.container(border=True):
        c1, c2, c3 = st.columns([0.5, 2.5, 0.6])
        with c1:
            if img and os.path.exists(img):
                st.image(img, width=80)
            else:
                st.markdown(f"### {icon}")
        with c2:
            st.markdown(f"**{icon} {类型}** | {time_str} | #{m['id']}")
            detail = m.get("一句话","") or generate_summary(m)
            st.caption(detail[:120])
            if 标签:
                tags_html = " ".join([f"`{t}`" for t in 标签[:6]])
                st.markdown(tags_html, unsafe_allow_html=True)
        with c3:
            if st.button("🔍 详情", key=f"detail_{m['id']}"):
                st.session_state.selected_memory = m
                st.rerun()
            if st.button("🗑️", key=f"del_{m['id']}"):
                delete_memory_with_image(m["id"])
                st.rerun()


def _show_detail(m: dict):
    with st.container(border=True):
        st.subheader(f"#{m['id']} {ICON_MAP.get(m.get('类型',''),'📋')} {m.get('类型','')}")
        img = m.get("图片路径","")
        if img and os.path.exists(img):
            st.image(img, width=400)

        info = m.get("信息",{})
        st.json(info)

        # 关联记忆
        with st.spinner("🔗 查找关联记忆..."):
            all_mems = get_recent_memories(50)
            related = find_relationships(m, all_mems)

        if related:
            st.subheader("🔗 关联记忆")
            for r in related[:5]:
                rel_id = r.get("id")
                reason = r.get("关联原因","")
                rel_mem = get_memory_by_id(rel_id)
                if rel_mem:
                    st.caption(f"#{rel_id} [{rel_mem.get('类型','')}] {reason} → {generate_summary(rel_mem)[:60]}")

        if st.button("关闭", key="close_detail"):
            st.session_state.selected_memory = None
            st.rerun()


# ============================================================
# Tab 3: 出游相册（GPS分组 + 时间聚类）
# ============================================================
def tab_trips():
    st.header("🏔️ 出游相册")
    st.caption("照片按 GPS 位置+时间自动分组")

    groups = get_trips_grouped_by_location()
    if not groups:
        st.info("还没有出游照片。用手机拍的照片自带 GPS，上传后会自动按地点分组。")
        return

    for location, photos in groups.items():
        with st.expander(f"📍 **{location}** ({len(photos)} 张)", expanded=len(groups) <= 3):
            # 时间聚类：同一天的分一起
            time_groups = {}
            for p in photos:
                info = p.get("信息",{})
                t = info.get("拍摄时间","") or p.get("创建时间","")
                date = t[:10] if t else "未知日期"
                if date not in time_groups: time_groups[date] = []
                time_groups[date].append(p)

            for date, day_photos in sorted(time_groups.items()):
                st.caption(f"📅 {date} ({len(day_photos)} 张)")
                cols = st.columns(min(len(day_photos), 5))
                for i, p in enumerate(day_photos):
                    with cols[i % 5]:
                        img_path = p.get("图片路径","")
                        if img_path and os.path.exists(img_path):
                            st.image(img_path, use_container_width=True)
                        st.caption(f"#{p['id']}")

                # 当天综合描述
                if len(day_photos) >= 2:
                    with st.expander(f"📊 综合分析 {date}"):
                        paths = [p.get("图片路径","") for p in day_photos if p.get("图片路径","") and os.path.exists(p.get("图片路径",""))]
                        if paths:
                            with st.spinner("分析中..."):
                                batch = analyze_batch(paths[:8])  # 最多8张
                            st.markdown(f"**{batch.get('组标题','')}**")
                            st.caption(batch.get("整体描述",""))


# ============================================================
# Tab 4: 每日总结
# ============================================================
def tab_daily():
    st.header("📊 每日总结")

    if st.button("🔄 生成今日总结", type="primary"):
        today_mems = get_today_memories()
        if not today_mems:
            st.info("今天还没有记录")
            return

        with st.spinner("AI 生成总结中..."):
            summary = generate_daily_summary(today_mems)

        st.markdown(f"### 🗓️ {datetime.now().strftime('%Y年%m月%d日')}")
        st.markdown(summary)

        # 分类明细
        st.divider()
        st.subheader("今日明细")
        types = {}
        for m in today_mems:
            t = m.get("类型","其他")
            if t not in types: types[t] = []
            types[t].append(m)

        for t, mems in sorted(types.items()):
            with st.expander(f"{ICON_MAP.get(t,'📋')} {t} ({len(mems)} 条)"):
                for m in mems:
                    st.caption(f"#{m['id']} {generate_summary(m)[:100]}")


# ============================================================
# Tab 5: 智能搜索
# ============================================================
def tab_search():
    st.header("🔍 智能搜索")
    c1, c2 = st.columns([1, 3])
    with c1:
        sf = st.selectbox("类型", ["全部","取件码","消费","灵感","聊天截图","出游照片","日程","文档","笔记","待办","其他"], key="search_filter")
    with c2:
        q = st.text_input("搜索", placeholder="白云山 / 火锅 / 取件码 / 上次和朋友去的那个地方...", label_visibility="collapsed")

    if q or sf != "全部":
        if not q and sf != "全部": results = get_memories_by_type(sf)
        elif q and sf == "全部": results = natural_search(q, 30)
        else: results = [m for m in natural_search(q, 50) if m.get("类型") == sf]

        if not results:
            st.info("没找到")
        else:
            st.write(f"找到 {len(results)} 条")
            for m in results:
                _render_search_result(m)


def _render_search_result(m: dict):
    类型 = m.get("类型","其他")
    icon = ICON_MAP.get(类型,"📋")
    信息 = m.get("信息",{})
    img = m.get("图片路径","")
    time_str = (m.get("创建时间","") or "")[:16]

    with st.container(border=True):
        c1, c2 = st.columns([1, 3])
        with c1:
            if img and os.path.exists(img):
                st.image(img, use_container_width=True)
            else:
                st.markdown(f"### {icon}")
        with c2:
            st.markdown(f"**{icon} {类型}** | {time_str} | #{m['id']}")
            detail = m.get("一句话","") or generate_summary(m)
            st.caption(detail[:150])
            if st.button("🗑️", key=f"search_del_{m['id']}"):
                delete_memory_with_image(m["id"])
                st.rerun()


# ============================================================
# Tab 6: 任务清单
# ============================================================
def tab_todos():
    st.header("⏰ 任务清单")
    todos = get_pending_tasks()

    if not todos: st.success("暂无待办 🎉")

    for m in todos:
        信息 = m.get("信息",{})
        img = m.get("图片路径","")
        mid = m["id"]
        time_str = (m.get("创建时间","") or "")[:16]

        with st.container(border=True):
            c1, c2, c3, c4 = st.columns([0.5, 1.5, 5, 1])
            with c1:
                if st.checkbox("✅", key=f"todo_{mid}"):
                    delete_memory_with_image(mid)
                    st.rerun()
            with c2:
                if img and os.path.exists(img):
                    st.image(img, width=100)
                else:
                    st.markdown("📦")
            with c3:
                st.markdown(f"**取件码: {信息.get('取件码','?')}**")
                st.caption(f"📍 {信息.get('快递点','?')} | {信息.get('取件方式','?')} | 🕐 {time_str}")
            with c4:
                if st.button("🗑️", key=f"tdel_{mid}"):
                    delete_memory_with_image(mid)
                    st.rerun()

    completed = get_completed_tasks()
    if completed:
        with st.expander(f"✅ 已完成 ({len(completed)})"):
            for m in completed:
                信息 = m.get("信息",{})
                st.caption(f"📦 {信息.get('取件码','?')} | {信息.get('快递点','?')}")
                if st.button("↩️ 恢复", key=f"undo_{m['id']}"):
                    mark_pending(m["id"])
                    st.rerun()


# ============================================================
# Tab 日程
# ============================================================

def tab_schedules():
    st.header("📅 日程")
    st.caption("AI 自动识别有时间信息的内容：活动海报、会议通知、车票、课程表等")

    schedules = get_schedules()
    if not schedules:
        st.info("还没有日程。上传含有时间信息的截图或文字（如活动海报、约会通知），AI 会自动识别。")
        return

    for m in schedules:
        信息 = m.get("信息",{})
        img = m.get("图片路径","")
        time_str = (m.get("创建时间","") or "")[:16]

        with st.container(border=True):
            c1, c2, c3 = st.columns([1.5, 5, 0.5])
            with c1:
                if img and os.path.exists(img):
                    st.image(img, width=120)
                else:
                    st.markdown("📅")
            with c2:
                event = 信息.get("事件","未知事件")
                start = 信息.get("开始时间","")
                location = 信息.get("地点","")
                note = 信息.get("备注","")
                st.markdown(f"### {event}")
                if start: st.caption(f"🕐 {start}")
                if location: st.caption(f"📍 {location}")
                if note: st.caption(f"📝 {note}")
                st.caption(f"记录于 {time_str}  #{m['id']}")
            with c3:
                if st.button("🗑️", key=f"sched_del_{m['id']}"):
                    delete_memory_with_image(m["id"])
                    st.rerun()


# ============================================================
# Tab 标签管理
# ============================================================

def tab_tags():
    st.header("🏷️ 标签管理")

    # ---- 预设标签 ----
    st.subheader("我的标签库")
    st.caption("在这里预设标签，AI 分析时会优先使用这些标签")

    user_tags = load_user_tags()
    new_tag = st.text_input("添加新标签", placeholder="输入标签名，回车添加", key="new_tag_input")

    if new_tag and new_tag not in user_tags:
        user_tags.append(new_tag)
        save_user_tags(user_tags)
        st.rerun()

    if user_tags:
        cols = st.columns(min(len(user_tags), 6))
        for i, tag in enumerate(user_tags):
            with cols[i % 6]:
                c1, c2 = st.columns([4, 1])
                c1.code(tag)
                if c2.button("✕", key=f"rmtag_{tag}"):
                    user_tags.remove(tag)
                    save_user_tags(user_tags)
                    st.rerun()
    else:
        st.caption("还没有预设标签，添加一些吧（比如：工作、学习、运动、美食、旅行）")

    st.divider()

    # ---- 全部标签云 ----
    st.subheader("全部标签")
    all_tags = get_all_tags()
    if all_tags:
        # 按使用次数排
        tags_html = " ".join([
            f'<span style="display:inline-block;background:#f0f0f0;padding:4px 12px;border-radius:16px;margin:4px;font-size:{max(0.8,min(1.5,1+count/20))}em;cursor:pointer;">{tag}<sup style="color:#999;font-size:0.7em;">{count}</sup></span>'
            for tag, count in all_tags.items()
        ])
        st.markdown(tags_html, unsafe_allow_html=True)

        # 点击标签查看相关记忆
        selected_tag = st.selectbox("按标签筛选记忆", ["—"] + list(all_tags.keys()))
        if selected_tag != "—":
            mems = get_memories_by_tag(selected_tag)
            st.write(f"**{selected_tag}** 相关 ({len(mems)} 条):")
            for m in mems:
                _render_search_result(m)

    # ---- 编辑记忆标签 ----
    st.divider()
    st.subheader("编辑记忆标签")
    mem_id = st.number_input("输入记忆 ID", min_value=1, step=1, key="edit_tag_id")
    if mem_id:
        mem = get_memory_by_id(mem_id)
        if mem:
            st.caption(f"当前: [{mem.get('类型','')}] {generate_summary(mem)[:80]}")
            current_tags = mem.get("标签",[])
            if isinstance(current_tags, str):
                try: current_tags = json.loads(current_tags)
                except: current_tags = []

            import json
            new_tags_str = st.text_input("标签（逗号分隔）", value=",".join(current_tags), key=f"edit_tags_{mem_id}")
            new_type = st.selectbox("修改类型", list(ICON_MAP.keys()), index=list(ICON_MAP.keys()).index(mem.get("类型","其他")) if mem.get("类型","其他") in ICON_MAP else 0, key=f"edit_type_{mem_id}")

            if st.button("💾 保存", key=f"save_tags_{mem_id}"):
                update_tags(mem_id, [t.strip() for t in new_tags_str.split(",") if t.strip()])
                if new_type != mem.get("类型"):
                    update_type(mem_id, new_type)
                st.success("已保存")
                st.rerun()
        else:
            st.warning("找不到这条记忆")


# ============================================================
# 主程序
# ============================================================
def main():
    init_db()
    render_sidebar()

    tabs = st.tabs([
        "📸 录入记忆", "📋 浏览记忆", "🏔️ 出游相册",
        "📊 每日总结", "📅 日程", "🏷️ 标签管理",
        "🔍 智能搜索", "⏰ 任务清单"
    ])

    with tabs[0]: tab_upload()
    with tabs[1]: tab_browse()
    with tabs[2]: tab_trips()
    with tabs[3]: tab_daily()
    with tabs[4]: tab_schedules()
    with tabs[5]: tab_tags()
    with tabs[6]: tab_search()
    with tabs[7]: tab_todos()

if __name__ == "__main__":
    main()
