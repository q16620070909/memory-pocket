"""
记忆口袋 —— 本地存储层
用 SQLite 存所有记忆：图片路径 + AI 分析结果 + 时间戳
"""

import sqlite3
import json
import os
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).parent / "memories.db"
IMAGE_DIR = Path(__file__).parent / "images"


def get_db():
    """获取数据库连接（自动创建表）。"""
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """初始化数据库（首次运行时建表）。"""
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS memories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            类型 TEXT NOT NULL,
            标签 TEXT,
            信息 TEXT,
            图片路径 TEXT,
            缩略图路径 TEXT,
            创建时间 TEXT NOT NULL,
            更新时间 TEXT NOT NULL
        )
    """)
    # 为旧数据库补加"已完成"字段
    try:
        conn.execute("ALTER TABLE memories ADD COLUMN 已完成 INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass  # 字段已存在
    conn.commit()
    conn.close()

    # 确保图片存储目录存在
    IMAGE_DIR.mkdir(exist_ok=True)


def save_memory(image_path: str, ai_result: dict) -> int:
    """
    保存一条记忆到数据库。

    参数:
        image_path: 原始图片路径
        ai_result: analyze_image() 返回的字典

    返回:
        int: 新记录的 ID
    """
    conn = get_db()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # 把列表/字典转成 JSON 字符串存
    标签_str = json.dumps(ai_result.get("标签", []), ensure_ascii=False)
    信息_str = json.dumps(ai_result.get("信息", {}), ensure_ascii=False)

    cursor = conn.execute(
        """INSERT INTO memories (类型, 标签, 信息, 图片路径, 创建时间, 更新时间)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (ai_result.get("类型", "其他"), 标签_str, 信息_str,
         image_path, now, now)
    )
    conn.commit()
    memory_id = cursor.lastrowid
    conn.close()
    return memory_id


def get_all_memories(limit: int = 100) -> list[dict]:
    """获取所有记忆（按时间倒序）。"""
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM memories ORDER BY 创建时间 DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()

    return [_row_to_dict(r) for r in rows]


def get_memories_by_type(类型: str, limit: int = 100) -> list[dict]:
    """按类型筛选记忆。"""
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM memories WHERE 类型 = ? ORDER BY 创建时间 DESC LIMIT ?",
        (类型, limit)
    ).fetchall()
    conn.close()

    return [_row_to_dict(r) for r in rows]


def search_memories(keyword: str, limit: int = 50) -> list[dict]:
    """用关键词搜索记忆（搜标签 + 信息内容 + 类型）。"""
    conn = get_db()
    keyword_like = f"%{keyword}%"
    rows = conn.execute(
        """SELECT * FROM memories
           WHERE 类型 LIKE ? OR 标签 LIKE ? OR 信息 LIKE ?
           ORDER BY 创建时间 DESC LIMIT ?""",
        (keyword_like, keyword_like, keyword_like, limit)
    ).fetchall()
    conn.close()

    return [_row_to_dict(r) for r in rows]


def get_pending_tasks() -> list[dict]:
    """获取所有未完成的待办（取件码等）。"""
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM memories WHERE 类型 = '取件码' AND 已完成 = 0 ORDER BY 创建时间 DESC"
    ).fetchall()
    conn.close()
    return [_row_to_dict(r) for r in rows]


def get_completed_tasks() -> list[dict]:
    """获取已完成的待办。"""
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM memories WHERE 类型 = '取件码' AND 已完成 = 1 ORDER BY 创建时间 DESC"
    ).fetchall()
    conn.close()
    return [_row_to_dict(r) for r in rows]


def mark_completed(memory_id: int) -> bool:
    """标记任务为已完成。"""
    conn = get_db()
    conn.execute(
        "UPDATE memories SET 已完成 = 1, 更新时间 = datetime('now','localtime') WHERE id = ?",
        (memory_id,)
    )
    conn.commit()
    conn.close()
    return True


def mark_pending(memory_id: int) -> bool:
    """取消完成，恢复为待办。"""
    conn = get_db()
    conn.execute(
        "UPDATE memories SET 已完成 = 0, 更新时间 = datetime('now','localtime') WHERE id = ?",
        (memory_id,)
    )
    conn.commit()
    conn.close()
    return True


def delete_memory_with_image(memory_id: int) -> bool:
    """删除记忆及其图片文件。"""
    conn = get_db()
    row = conn.execute("SELECT 图片路径 FROM memories WHERE id = ?", (memory_id,)).fetchone()
    if row and row["图片路径"]:
        img_path = row["图片路径"]
        if os.path.exists(img_path):
            os.remove(img_path)
    conn.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
    conn.commit()
    conn.close()
    return True


def get_inspirations() -> list[dict]:
    """获取所有灵感笔记。"""
    return get_memories_by_type("灵感")


def get_trip_albums() -> list[dict]:
    """获取所有出游照片。"""
    return get_memories_by_type("出游照片")


def get_trips_grouped_by_location() -> dict:
    """
    按 GPS 地点名分组出游照片。
    同地点的照片归为一个相册。

    返回:
        { "广州白云山": [记忆1, 记忆2, ...], "深圳湾": [...], "未知地点": [...] }
    """
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM memories WHERE 类型 = '出游照片' ORDER BY 创建时间 DESC"
    ).fetchall()
    conn.close()

    groups = {}
    for r in rows:
        m = _row_to_dict(r)
        信息 = m.get("信息", {})
        # 分组依据：GPS地点 > AI识别地点 > 未知
        loc = m.get("GPS地点", "") or 信息.get("地点", "") or "未知地点"
        if loc not in groups:
            groups[loc] = []
        groups[loc].append(m)

    # 有 GPS 的排前面
    sorted_groups = {}
    for loc in sorted(groups.keys(), key=lambda x: (x == "未知地点", x)):
        sorted_groups[loc] = groups[loc]

    return sorted_groups


def get_expenses() -> list[dict]:
    """获取所有消费记录。"""
    return get_memories_by_type("消费")


def save_text_memory(text: str, ai_result: dict) -> int:
    """保存纯文本记忆（无图片）。"""
    conn = get_db()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    标签_str = json.dumps(ai_result.get("标签", []), ensure_ascii=False)
    信息_str = json.dumps(ai_result.get("信息", {}), ensure_ascii=False)

    cursor = conn.execute(
        """INSERT INTO memories (类型, 标签, 信息, 图片路径, 创建时间, 更新时间)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (ai_result.get("类型", "笔记"), 标签_str, 信息_str, "", now, now)
    )
    conn.commit()
    memory_id = cursor.lastrowid
    conn.close()
    return memory_id


def get_today_memories() -> list[dict]:
    """获取今天的记忆。"""
    today = datetime.now().strftime("%Y-%m-%d")
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM memories WHERE 创建时间 LIKE ? ORDER BY 创建时间 DESC",
        (f"{today}%",)
    ).fetchall()
    conn.close()
    return [_row_to_dict(r) for r in rows]


def get_recent_memories(limit: int = 50) -> list[dict]:
    """获取最近的记忆（用于关联分析）。"""
    return get_all_memories(limit)


def get_memory_by_id(memory_id: int) -> dict | None:
    """按 ID 获取单条记忆。"""
    conn = get_db()
    row = conn.execute("SELECT * FROM memories WHERE id = ?", (memory_id,)).fetchone()
    conn.close()
    return _row_to_dict(row) if row else None


def update_tags(memory_id: int, tags: list[str]) -> bool:
    """更新一条记忆的标签。"""
    conn = get_db()
    conn.execute(
        "UPDATE memories SET 标签 = ?, 更新时间 = datetime('now','localtime') WHERE id = ?",
        (json.dumps(tags, ensure_ascii=False), memory_id)
    )
    conn.commit()
    conn.close()
    return True


def update_type(memory_id: int, new_type: str) -> bool:
    """更新一条记忆的类型。"""
    conn = get_db()
    conn.execute(
        "UPDATE memories SET 类型 = ?, 更新时间 = datetime('now','localtime') WHERE id = ?",
        (new_type, memory_id)
    )
    conn.commit()
    conn.close()
    return True


def get_memories_by_tag(tag: str, limit: int = 100) -> list[dict]:
    """按标签搜索记忆。"""
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM memories WHERE 标签 LIKE ? ORDER BY 创建时间 DESC LIMIT ?",
        (f"%{tag}%", limit)
    ).fetchall()
    conn.close()
    return [_row_to_dict(r) for r in rows]


def get_all_tags() -> dict:
    """获取所有使用的标签及其出现次数。"""
    conn = get_db()
    rows = conn.execute("SELECT 标签 FROM memories").fetchall()
    conn.close()
    tag_counts = {}
    for r in rows:
        try:
            tags = json.loads(r["标签"]) if isinstance(r["标签"], str) else (r["标签"] or [])
            for t in tags:
                tag_counts[t] = tag_counts.get(t, 0) + 1
        except Exception:
            pass
    return dict(sorted(tag_counts.items(), key=lambda x: x[1], reverse=True))


def get_schedules() -> list[dict]:
    """获取所有日程（按开始时间排序）。"""
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM memories WHERE 类型 = '日程' ORDER BY 创建时间 DESC"
    ).fetchall()
    conn.close()
    return [_row_to_dict(r) for r in rows]


def delete_memory(memory_id: int) -> bool:
    """删除一条记忆。"""
    conn = get_db()
    conn.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
    conn.commit()
    conn.close()
    return True


def get_statistics() -> dict:
    """获取统计信息。"""
    conn = get_db()
    total = conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
    by_type = conn.execute(
        "SELECT 类型, COUNT(*) as cnt FROM memories GROUP BY 类型"
    ).fetchall()
    conn.close()

    return {
        "总记忆数": total,
        "分类统计": {r["类型"]: r["cnt"] for r in by_type}
    }


def _row_to_dict(row: sqlite3.Row) -> dict:
    """把数据库行转成字典，并解析 JSON 字段。"""
    d = dict(row)
    for field in ["标签", "信息"]:
        if field in d and isinstance(d[field], str):
            try:
                d[field] = json.loads(d[field])
            except json.JSONDecodeError:
                pass
    return d


# 首次加载时初始化
init_db()
