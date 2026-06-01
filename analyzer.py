"""
记忆口袋 —— 核心分析引擎 v5.0
图片 | 文字 | 语音 | 多图 | 自定义标签 | 日程识别 | 关联记忆 | 每日总结
"""

import os
import base64
import json
from pathlib import Path
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

# Streamlit Cloud 用 st.secrets，本地用 .env
def _get_api_key():
    try:
        import streamlit as st
        return st.secrets["ZHIPU_API_KEY"]
    except Exception:
        return os.getenv("ZHIPU_API_KEY", "3b7fe9a4fcba4bc789c2920fb75c49ad.P9jy6lrtKTSl7ZPy")

def _get_base_url():
    try:
        import streamlit as st
        return st.secrets.get("ZHIPU_BASE_URL", "https://open.bigmodel.cn/api/paas/v4/")
    except Exception:
        return os.getenv("ZHIPU_BASE_URL", "https://open.bigmodel.cn/api/paas/v4/")

client = OpenAI(api_key=_get_api_key(), base_url=_get_base_url(), timeout=60, max_retries=2)

VISION_MODEL = "glm-4v-flash"   # 智谱免费多模态模型
TEXT_MODEL = "glm-4-flash"      # 智谱免费文本模型

# ============================================================
# 标签配置管理
# ============================================================

TAGS_FILE = Path(__file__).parent / "tags.json"


def load_user_tags() -> list[str]:
    """加载用户预设标签。"""
    try:
        if TAGS_FILE.exists():
            with open(TAGS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get("标签", [])
    except Exception:
        pass
    return []


def save_user_tags(tags: list[str]):
    """保存用户预设标签。"""
    with open(TAGS_FILE, "w", encoding="utf-8") as f:
        json.dump({"标签": list(set(tags))}, f, ensure_ascii=False, indent=2)


def _build_tag_instructions() -> str:
    """构建标签提示语——如果用户有预设标签，优先用。"""
    user_tags = load_user_tags()
    if user_tags:
        tag_list = "、".join(user_tags)
        return f"""## 标签规则
用户预设了这些标签：{tag_list}
打标签时优先使用预设标签，如果内容匹配不上再创建新标签。每条记忆 3-6 个标签。"""
    else:
        return "## 标签规则\n为每条记忆生成 3-6 个中文标签。"


def _build_prompt(base: str) -> str:
    """动态拼接 prompt：基础规则 + 用户标签规则。"""
    return base + "\n" + _build_tag_instructions()

# ============================================================
# SYSTEM PROMPTS
# ============================================================

SYSTEM_PROMPT_VISION = """你是"记忆口袋"App 的 AI 管家。你会看到一张图片。判断类型+提取信息。只返回 JSON。

## 类型
- "取件码": 快递取件码截图。即使有"未发出/系统关闭"等免责声明，仍归类为取件码，只提取数字编号。
- "消费": 支付/账单/付款记录
- "灵感": 有思想的内容、想法、备忘
- "聊天截图": 对话记录
- "出游照片": 风景/人物照片
- "日程": 包含时间/日期/活动安排/会议/约会的截图。比如：活动海报上的时间地点、日历截图、通知上的会议时间、课程表、车票/机票
- "文档": 合同/证件/票据
- "待办": 明确需要做的事、提醒、任务
- "其他": 以上都不匹配

## 提取规则
### 取件码
{"取件码":"纯数字编号"}

### 消费
{"金额":数字,"商户":"名称","支付方式":"微信/支付宝等"}

### 灵感
{"标题":"概括","内容":"完整文字","来源":"原创/截图自哪个App"}

### 聊天截图
{"发言人":["A","B"],"内容摘要":"概括","平台":"微信/QQ等"}

### 出游照片
{"地点":"识别或未知","场景描述":"画面描述","人物数量":0}

### 日程(重要！)
从图中提取所有与时间相关的信息。{"事件":"什么活动/会议/约会","开始时间":"YYYY-MM-DD HH:MM 或文字描述","结束时间":"如有","地点":"如有","备注":"其他信息"}
例如看到活动海报→{"事件":"XX讲座","开始时间":"2025-06-15 14:00","结束时间":"","地点":"图书馆报告厅","备注":"需要提前报名"}

### 待办
{"任务":"具体要做什么","截止时间":"如有","优先级":"高/中/低"}

### 文档
{"文档类型":"合同/票据等","关键信息":"摘要"}

### 其他
{"内容":"描述","猜测用途":"推测"}

## 返回(只返回JSON)
{"类型":"...","标签":["标签1","标签2","标签3"],"信息":{...},"一句话":"用一句话概括"}
"""

SYSTEM_PROMPT_TEXT = """你是"记忆口袋"App 的 AI 管家。用户输入了一段文字。判断类型+提取信息。只返回 JSON。

## 类型
- "灵感": 想法、创意、备忘
- "消费": 金额/支付/账单
- "待办": 需要做的事、提醒
- "日程": 含有时间/日期的活动安排。如"周五下午3点开会""6月15日去北京"
- "笔记": 一般记录、日志
- "聊天记录": 对话
- "其他": 不匹配以上

## 提取规则
### 灵感
{"标题":"概括","内容":"完整原文"}
### 消费
{"金额":数字,"商户":"名称"}
### 待办
{"任务":"具体任务","截止时间":"如有","优先级":"高/中/低"}
### 日程
{"事件":"什么活动","开始时间":"YYYY-MM-DD HH:MM或描述","结束时间":"如有","地点":"如有"}
### 笔记
{"标题":"概括","内容":"完整原文"}
### 聊天记录
{"发言人":["A","B"],"内容摘要":"概括","平台":"如提到"}
### 其他
{"内容":"原文","猜测用途":"推测"}

## 返回(只返回JSON)
{"类型":"...","标签":["标签1","标签2","标签3"],"信息":{...},"一句话":"用一句话概括"}
"""

SYSTEM_PROMPT_BATCH = """你是"记忆口袋"App 的 AI 管家。用户一次上传了多张照片，这些照片可能来自同一次出游、同一天的活动。请：

1. 判断这组照片的整体类型（出游/活动/聚会/日常等）
2. 如果有GPS信息，结合位置推断行程
3. 按时间顺序串成一个故事
4. 提取共同的标签

返回 JSON：
{
  "组类型":"出游/聚会/活动/日常",
  "组标题":"比如：2024年6月白云山爬山之旅",
  "照片分析":[
    {"序号":1,"场景":"这张照片的内容","时间":"如有GPS时间"},
    {"序号":2,"场景":"..."}
  ],
  "整体描述":"用一段话描述这组照片记录了什么",
  "共同标签":["标签1","标签2","标签3"],
  "地点":"如果有GPS/场景推断的地点",
  "时间跨度":"从...到..."
}
"""

SYSTEM_PROMPT_LINK = """你是"记忆口袋"AI。以下是一个用户的所有记忆列表。请找出与目标记忆最相关的其他记忆。

目标记忆: {target}

所有记忆:
{all_memories}

找出和目标记忆最相关的 3-5 条其他记忆。关联依据：时间接近、地点相同、标签重叠、内容逻辑相关（比如"买登山装备的消费"和"爬山出游"相关）。

只返回 JSON 数组：
[{"id":记忆ID,"关联原因":"为什么相关(一句话)"}, ...]
"""

SYSTEM_PROMPT_SUMMARY = """你是"记忆口袋"AI。以下是用户今天的所有记忆。写一段200字以内的今日小结。

{memories}

用温暖、贴近的语气，像朋友在帮你回顾今天。包含：
- 今天主要做了什么
- 有什么亮点
- 待办还剩下什么

只返回文本，不要JSON。
"""


# ============================================================
# 核心函数
# ============================================================

def analyze_image(image_path: str) -> dict:
    """分析一张图片 → 类型+标签+信息"""
    exif = extract_exif(image_path)

    with open(image_path, "rb") as f:
        image_data = base64.b64encode(f.read()).decode("utf-8")

    ext = Path(image_path).suffix.lower()
    mime_map = {".jpg":"image/jpeg",".jpeg":"image/jpeg",".png":"image/png",".webp":"image/webp"}
    mime_type = mime_map.get(ext, "image/jpeg")
    data_url = f"data:{mime_type};base64,{image_data}"

    try:
        response = client.chat.completions.create(
            model=VISION_MODEL,
            messages=[
                {"role":"system","content":_build_prompt(SYSTEM_PROMPT_VISION)},
                {"role":"user","content":[
                    {"type":"image_url","image_url":{"url":data_url}},
                    {"type":"text","text":"看这张图，返回JSON。"}
                ]}
            ],
            temperature=0.3, max_tokens=1000,
        )
        result_text = response.choices[0].message.content.strip()
        if result_text.startswith("```"): result_text = result_text.split("\n",1)[1].rstrip("```")
        result = json.loads(result_text)

        if exif:
            info = result.get("信息",{})
            if exif.get("地点名") and not info.get("地点"):
                info["地点"] = exif["地点名"]
            info["GPS纬度"] = exif.get("纬度")
            info["GPS经度"] = exif.get("经度")
            info["拍摄时间"] = exif.get("拍摄时间", info.get("拍摄时间",""))
            result["GPS地点"] = exif.get("地点名","")
            result["信息"] = info

        return result
    except Exception as e:
        import traceback
        return {"类型":"其他","标签":["分析失败"],"信息":{"错误":str(e)},"一句话":"分析失败"}


def analyze_text(text: str) -> dict:
    """分析一段纯文字 → 类型+标签+信息。用于文字输入和语音转录后处理。"""
    try:
        response = client.chat.completions.create(
            model=TEXT_MODEL,
            messages=[
                {"role":"system","content":_build_prompt(SYSTEM_PROMPT_TEXT)},
                {"role":"user","content":f"以下是用户输入的文字：\n\n{text}\n\n分析并返回JSON。"}
            ],
            temperature=0.3, max_tokens=800,
        )
        result_text = response.choices[0].message.content.strip()
        if result_text.startswith("```"): result_text = result_text.split("\n",1)[1].rstrip("```")
        return json.loads(result_text)
    except Exception as e:
        return {"类型":"笔记","标签":["文字输入"],"信息":{"标题":"文字记录","内容":text[:500]},"一句话":text[:50]}


def analyze_batch(image_paths: list[str]) -> dict:
    """一组照片 → 整体分析+每张简述+共同标签"""
    if len(image_paths) == 1:
        return analyze_image(image_paths[0])

    # 为每张图提取 EXIF
    exif_data = {}
    image_parts = []
    for i, path in enumerate(image_paths):
        exif = extract_exif(path)
        exif_data[i] = exif
        with open(path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode("utf-8")
        ext = Path(path).suffix.lower()
        mime_map = {".jpg":"image/jpeg",".jpeg":"image/jpeg",".png":"image/png",".webp":"image/webp"}
        mime = mime_map.get(ext,"image/jpeg")
        loc_info = f"(GPS: {exif.get('地点名','未知')}, 时间: {exif.get('拍摄时间','未知')})" if exif else ""
        image_parts.append({
            "type":"image_url","image_url":{"url":f"data:{mime};base64,{b64}"}
        })
        image_parts.append({
            "type":"text","text":f"照片{i+1} {loc_info}"
        })

    try:
        response = client.chat.completions.create(
            model=VISION_MODEL,
            messages=[
                {"role":"system","content":SYSTEM_PROMPT_BATCH},
                {"role":"user","content":[
                    *image_parts,
                    {"type":"text","text":"分析这组照片，返回JSON。"}
                ]}
            ],
            temperature=0.3, max_tokens=2000,
        )
        result_text = response.choices[0].message.content.strip()
        if result_text.startswith("```"): result_text = result_text.split("\n",1)[1].rstrip("```")
        return json.loads(result_text)
    except Exception as e:
        return {"组类型":"日常","组标题":"未命名相册","照片分析":[],"整体描述":f"分析失败: {e}","共同标签":[],"地点":"未知"}


def transcribe_audio(audio_bytes: bytes) -> str:
    """语音转文字。用 OpenRouter 的 Whisper 模型。"""
    import tempfile
    try:
        # 保存为临时 WAV
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp.write(audio_bytes)
            tmp_path = tmp.name

        # 用 openai 库调 Whisper
        audio_client = OpenAI(
            api_key=os.getenv("OPENROUTER_API_KEY"),
            base_url=os.getenv("OPENROUTER_BASE_URL"),
        )
        with open(tmp_path, "rb") as audio_file:
            transcript = audio_client.audio.transcriptions.create(
                model="openai/whisper-large-v3-turbo",
                file=audio_file,
                language="zh",
            )
        os.unlink(tmp_path)
        return transcript.text
    except Exception:
        # Fallback: 用 local whisper 或返回提示
        try:
            import whisper
            model = whisper.load_model("tiny")
            result = model.transcribe(tmp_path, language="zh")
            os.unlink(tmp_path)
            return result["text"]
        except Exception:
            return "语音转文字失败，请手动输入"


def find_relationships(target_memory: dict, all_memories: list[dict]) -> list[dict]:
    """AI 找出与目标记忆关联的其他记忆。"""
    if len(all_memories) < 2:
        return []

    target_str = json.dumps({
        "id": target_memory["id"],
        "类型": target_memory.get("类型",""),
        "标签": target_memory.get("标签",[]),
        "信息": str(target_memory.get("信息",{}))[:200],
        "时间": target_memory.get("创建时间",""),
    }, ensure_ascii=False)

    memories_str = json.dumps([{
        "id": m["id"],
        "类型": m.get("类型",""),
        "标签": m.get("标签",[]),
        "信息": str(m.get("信息",{}))[:150],
        "时间": m.get("创建时间",""),
    } for m in all_memories if m["id"] != target_memory["id"]], ensure_ascii=False)

    try:
        response = client.chat.completions.create(
            model=TEXT_MODEL,
            messages=[{
                "role":"user",
                "content": SYSTEM_PROMPT_LINK.format(target=target_str, all_memories=memories_str)
            }],
            temperature=0.3, max_tokens=500,
        )
        text = response.choices[0].message.content.strip()
        if text.startswith("```"): text = text.split("\n",1)[1].rstrip("```")
        return json.loads(text)
    except Exception:
        return []


def generate_daily_summary(memories: list[dict]) -> str:
    """根据今日记忆生成一段小结。"""
    if not memories:
        return "今天还没有记录什么，去上传点什么吧 🌟"

    mem_text = "\n".join([
        f"- [{m.get('类型','')}] {m.get('一句话',str(m.get('信息',{}))[:80])}"
        for m in memories[:20]
    ])

    try:
        response = client.chat.completions.create(
            model=TEXT_MODEL,
            messages=[{
                "role":"user",
                "content": SYSTEM_PROMPT_SUMMARY.format(memories=mem_text)
            }],
            temperature=0.7, max_tokens=300,
        )
        return response.choices[0].message.content.strip()
    except Exception:
        types = {}
        for m in memories:
            t = m.get("类型","其他")
            types[t] = types.get(t,0)+1
        type_summary = "、".join([f"{k}{v}条" for k,v in types.items()])
        return f"今天共记录了 {len(memories)} 条记忆：{type_summary}。打开 App 查看详情～"


# ============================================================
# GPS / EXIF
# ============================================================

def extract_exif(image_path: str) -> dict:
    from PIL import Image
    from PIL.ExifTags import TAGS, GPSTAGS
    try:
        img = Image.open(image_path)
        exif_data = img._getexif()
        if not exif_data: return {}

        exif = {}
        for tag_id, value in exif_data.items():
            exif[TAGS.get(tag_id, tag_id)] = value

        result = {}
        if "DateTimeOriginal" in exif: result["拍摄时间"] = exif["DateTimeOriginal"]
        elif "DateTime" in exif: result["拍摄时间"] = exif["DateTime"]

        gps_info = exif_data.get(34853)
        if gps_info:
            gps = {}
            for key, val in gps_info.items():
                gps[GPSTAGS.get(key, key)] = val
            if "GPSLatitude" in gps and "GPSLongitude" in gps:
                lat = _to_decimal(gps["GPSLatitude"], gps.get("GPSLatitudeRef","N"))
                lon = _to_decimal(gps["GPSLongitude"], gps.get("GPSLongitudeRef","E"))
                result["纬度"] = round(lat, 6)
                result["经度"] = round(lon, 6)
                place = _reverse_geocode(lat, lon)
                if place: result["地点名"] = place
        return result
    except Exception:
        return {}

def _to_decimal(dms, ref):
    d,m,s = dms
    dec = float(d)+float(m)/60+float(s)/3600
    return -dec if ref in ("S","W") else dec

def _reverse_geocode(lat, lon):
    try:
        from geopy.geocoders import Nominatim
        loc = Nominatim(user_agent="memory-pocket").reverse(f"{lat},{lon}", language="zh", timeout=5)
        if loc:
            addr = loc.raw.get("address",{})
            city = addr.get("city","") or addr.get("town","") or addr.get("county","")
            dist = addr.get("district","") or addr.get("suburb","")
            return f"{city}{dist}" if city and dist else (city or addr.get("display_name","")[:50])
    except Exception: pass
    return ""

# ============================================================
# 两轮 AI 分析（App 内部自动完成，用户无感）
# ============================================================

ROUND1_PROMPT = """你是一张图片的初步分析器。仔细看这张图，用一句 JSON 回答：

1. 图中有什么内容？（文字、场景、人物等）
2. 图中包含哪些可提取的关键信息？
3. 它最适合归为哪种类型？

类型选项：取件码 / 消费 / 日程 / 灵感 / 待办 / 出游照片 / 聊天截图 / 文档 / 其他

只返回 JSON：
{"描述":"图中内容的描述","可提取信息":["信息A","信息B","信息C"],"推荐类型":"取件码","关键词":["关键词"]}
"""

ROUND2_PROMPTS = {
    "取件码": "你是取件码提取器。从图中只提取快递取件码的纯数字编号。返回JSON：{\"取件码\":\"编号\"}",
    "消费": "你是消费记录提取器。从图中提取消费信息。返回JSON：{\"金额\":数字,\"商户\":\"名称\",\"支付方式\":\"方式\"}",
    "日程": "你是日程提取器。从图中提取时间相关信息。返回JSON：{\"事件\":\"什么活动\",\"开始时间\":\"时间\",\"地点\":\"地点\"}",
    "灵感": "你是灵感提取器。提取图中的文字内容作为灵感。返回JSON：{\"标题\":\"概括\",\"内容\":\"完整文字\"}",
    "待办": "你是待办提取器。提取图中需要做的事。返回JSON：{\"任务\":\"具体任务\",\"截止时间\":\"如有\"}",
    "出游照片": "你是出游照片分析器。描述照片场景。返回JSON：{\"地点\":\"地点\",\"场景描述\":\"画面描述\"}",
    "聊天截图": "你是聊天记录提取器。提取对话内容。返回JSON：{\"发言人\":[\"A\",\"B\"],\"内容摘要\":\"概括\"}",
    "文档": "你是文档提取器。提取文档关键信息。返回JSON：{\"文档类型\":\"类型\",\"关键信息\":\"摘要\"}",
    "其他": "你是通用信息提取器。从图中提取所有可见的文字和关键信息。返回JSON：{\"内容\":\"描述\",\"文字\":\"提取的文字\"}",
}


def analyze_image_two_pass(image_path: str) -> dict:
    """
    App 内部自动两轮 AI 对话：
    第1轮：AI 看图 → 识别类型 + 判断可提取什么
    第2轮：根据类型 → 用专用 prompt 精准提取

    用户只看到最终结果。
    """
    with open(image_path, "rb") as f:
        image_data = base64.b64encode(f.read()).decode("utf-8")

    ext = Path(image_path).suffix.lower()
    mime_map = {".jpg":"image/jpeg",".jpeg":"image/jpeg",".png":"image/png",".webp":"image/webp"}
    mime_type = mime_map.get(ext, "image/jpeg")
    data_url = f"data:{mime_type};base64,{image_data}"

    try:
        # ---- 第1轮：看图识别 ----
        r1 = client.chat.completions.create(
            model=VISION_MODEL,
            messages=[
                {"role":"system","content":ROUND1_PROMPT},
                {"role":"user","content":[{"type":"image_url","image_url":{"url":data_url}},{"type":"text","text":"分析这张图"}]}
            ],
            temperature=0.3, max_tokens=500,
        )
        r1_text = r1.choices[0].message.content.strip()
        if r1_text.startswith("```"): r1_text = r1_text.split("\n",1)[1].rstrip("```")
        r1_result = json.loads(r1_text)

        detected_type = r1_result.get("推荐类型", "其他")
        description = r1_result.get("描述", "")
        extractable = r1_result.get("可提取信息", [])
        keywords = r1_result.get("关键词", [])

        # ---- 第2轮：精准提取 ----
        r2_prompt = ROUND2_PROMPTS.get(detected_type, ROUND2_PROMPTS["其他"])
        # 把第1轮看到的内容告诉第2轮，让它知道上下文
        context = f"第1轮分析结果：这是一张{detected_type}。图中包含：{description}。可提取：{', '.join(extractable)}。现在精确提取信息。"

        r2 = client.chat.completions.create(
            model=VISION_MODEL,
            messages=[
                {"role":"system","content":r2_prompt},
                {"role":"user","content":[
                    {"type":"image_url","image_url":{"url":data_url}},
                    {"type":"text","text":context}
                ]}
            ],
            temperature=0.2, max_tokens=500,
        )
        r2_text = r2.choices[0].message.content.strip()
        if r2_text.startswith("```"): r2_text = r2_text.split("\n",1)[1].rstrip("```")
        r2_result = json.loads(r2_text)

        # 组装最终结果
        return {
            "类型": detected_type,
            "标签": keywords,
            "信息": r2_result,
            "一句话": description[:80],
            "_两轮分析": {"第1轮": r1_result, "第2轮": r2_result},
        }

    except Exception as e:
        import traceback
        return {"类型":"其他","标签":["分析失败"],"信息":{"错误":str(e)},"一句话":"分析失败"}


# ============================================================
# 对话式图片分析（AI 看图 → 提问 → 用户引导 → 精准提取）
# ============================================================

CONVERSATION_SYSTEM_PROMPT = """你是"记忆口袋"App 的 AI 管家。用户上传了一张图片，你会看到这张图。你的任务是通过对话引导用户，搞清楚用户想从这张图里提取什么信息。

## 对话规则

### 第一轮（首次对话）
1. 仔细看这张图，用一句话描述你看到了什么
2. 根据图片内容，给出 2-3 个你认为用户最可能想做的事（从下面选）
3. 最后问用户"你想用这张图做什么？"

可选的操作类型：提取取件码、记一笔消费、创建日程、记录灵感、添加待办、保存为出游照片、存档文档、或用户自定义

示例回复：
"我看到一张快递取件截图，上面显示菜鸟驿站和一个取件码数字。你想：
1. 📦 提取取件码
2. 📝 只记个备忘
3. 🤔 其他用途
告诉我你的想法～"

### 后续轮次
根据用户的回复，精确提取信息。只返回 JSON，不要解释。格式：
{"类型":"取件码/消费/日程/灵感/待办/出游照片/文档/笔记/其他","标签":["标签1","标签2"],"信息":{...},"一句话":"概括"}

如果用户说"就这个""可以了""存起来"等确认词，立即按之前讨论的方向提取信息并返回 JSON。
如果用户说"不对，重新看一下""再仔细看看"等，重新看图给新的判断。
"""


def analyze_image_conversation(image_path: str, chat_history: list[dict] | None = None) -> dict:
    """
    对话式图片分析。支持多轮对话，AI 看图后主动引导用户。

    参数:
        image_path: 图片路径
        chat_history: [{"role":"user","content":"..."}, {"role":"assistant","content":"..."}, ...]
                      如果为空或第一次调用，AI 会先描述图片并提问

    返回:
        dict: {"回复": "AI的文本回复", "结果": {...}或None}
              如果"结果"不为 None，说明 AI 已经完成了信息提取
    """
    with open(image_path, "rb") as f:
        image_data = base64.b64encode(f.read()).decode("utf-8")

    ext = Path(image_path).suffix.lower()
    mime_map = {".jpg":"image/jpeg",".jpeg":"image/jpeg",".png":"image/png",".webp":"image/webp"}
    mime_type = mime_map.get(ext, "image/jpeg")
    data_url = f"data:{mime_type};base64,{image_data}"

    is_first_turn = not chat_history or len(chat_history) == 0

    # 构建消息
    messages = [{"role":"system","content":CONVERSATION_SYSTEM_PROMPT}]

    # 添加历史对话 + 图片（图片只在第一条消息里带）
    if chat_history:
        for i, msg in enumerate(chat_history):
            if i == 0 and msg["role"] == "user":
                # 第一条用户消息带图片
                messages.append({
                    "role":"user",
                    "content":[
                        {"type":"image_url","image_url":{"url":data_url}},
                        {"type":"text","text":msg["content"]}
                    ]
                })
            else:
                messages.append({"role":msg["role"],"content":msg["content"]})
    else:
        # 首次对话：发图片 + 让AI描述并提问
        messages.append({
            "role":"user",
            "content":[
                {"type":"image_url","image_url":{"url":data_url}},
                {"type":"text","text":"看看这张图，告诉我你看到了什么，问我想做什么。"}
            ]
        })

    try:
        response = client.chat.completions.create(
            model=VISION_MODEL,
            messages=messages,
            temperature=0.5 if is_first_turn else 0.3,
            max_tokens=800,
        )

        ai_text = response.choices[0].message.content.strip()

        # 判断 AI 是否返回了 JSON（说明完成了提取）
        if ai_text.startswith("{"):
            # 清理 markdown
            if ai_text.startswith("```"):
                ai_text = ai_text.split("\n",1)[1].rstrip("```")
            try:
                result = json.loads(ai_text)
                return {"回复": f"已提取：{result.get('一句话','')}", "结果": result}
            except json.JSONDecodeError:
                pass

        return {"回复": ai_text, "结果": None}

    except Exception as e:
        return {"回复": f"分析出错: {e}", "结果": None}


def generate_summary(result: dict) -> str:
    return result.get("一句话", "") or str(result.get("信息",{}))[:80]
