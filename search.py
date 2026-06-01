"""
记忆口袋 —— 智能搜索引擎
支持关键词搜索 + 自然语言模糊搜索（OpenRouter）
"""

import json
from openai import OpenAI
import os
from pathlib import Path
from dotenv import load_dotenv
from storage import search_memories

load_dotenv(Path(__file__).parent / ".env")

def _get_zhipu_key():
    try:
        import streamlit as st
        return st.secrets["ZHIPU_API_KEY"]
    except Exception:
        return os.getenv("ZHIPU_API_KEY", "3b7fe9a4fcba4bc789c2920fb75c49ad.P9jy6lrtKTSl7ZPy")

client = OpenAI(api_key=_get_zhipu_key(), base_url="https://open.bigmodel.cn/api/paas/v4/", timeout=60, max_retries=2)


def natural_search(query: str, limit: int = 20) -> list[dict]:
    """智能搜索：关键词粗筛 + 自然语言关键词提取。"""
    results = search_memories(query, limit=50)

    if len(query) >= 5 and len(results) < 5:
        keywords = _extract_keywords(query)
        if keywords:
            all_results = {r["id"]: r for r in results}
            for kw in keywords:
                for r in search_memories(kw, limit=20):
                    all_results[r["id"]] = r
            results = list(all_results.values())

    if len(query) >= 2:
        searchable = lambda r: " ".join([
            r.get("类型", ""),
            str(r.get("标签", "")),
            str(r.get("信息", "")),
        ])
        results.sort(key=lambda r: searchable(r).count(query.lower()), reverse=True)

    return results[:limit]


def _extract_keywords(query: str) -> list[str]:
    """用 AI 把自然语言查询拆成搜索关键词。"""
    try:
        response = client.chat.completions.create(
            model="glm-4-flash",
            messages=[{
                "role": "system",
                "content": (
                    "用户在一个个人数据库里搜索。数据库类型：取件码、消费、灵感、聊天截图、出游照片、文档、其他。"
                    "把自然语言拆成3-6个搜索关键词，JSON数组返回。只返回JSON。"
                    "例：'上次和朋友爬山花的钱' -> ['爬山','消费','出游']"
                )
            }, {"role": "user", "content": query}],
            temperature=0.3,
            max_tokens=200,
        )

        text = response.choices[0].message.content.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1]
            if text.endswith("```"):
                text = text[:-3]

        keywords = json.loads(text)
        return keywords if isinstance(keywords, list) else []

    except Exception:
        import jieba
        return [w for w in jieba.lcut(query) if len(w) >= 2]
