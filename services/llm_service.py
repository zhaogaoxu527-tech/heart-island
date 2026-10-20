"""Kimi（Moonshot）大模型调用与本地体验模式。

Kimi 提供 OpenAI 兼容的 Chat Completions 接口：
    POST https://api.moonshot.cn/v1/chat/completions

系统人设、历史对话和当前消息会以标准 messages 发送。
kimi-k3 只允许 temperature=1，因此这里不发送 temperature，使用服务默认值。

模型不可用时，可通过 KIMI_FALLBACK_LOCAL=true 自动回退到内置角色回复，
不中断聊天；实际错误会写入服务端日志，不返回给浏览器。
"""

from __future__ import annotations

import hashlib
import logging
from typing import Any

import requests
from flask import current_app

from errors import ApiError

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 对外入口
# ---------------------------------------------------------------------------
def get_llm_mode() -> str:
    """返回当前回复来源：kimi（真实模型）或 demo（本地体验）。"""
    return "kimi" if current_app.config.get("KIMI_API_KEY") else "demo"


def get_llm_status() -> dict:
    """给前端展示的模型状态，不包含任何密钥。"""
    mode = get_llm_mode()
    return {
        "mode": mode,
        "model": current_app.config.get("KIMI_MODEL") if mode == "kimi" else None,
        "label": "Kimi 已配置" if mode == "kimi" else "本地体验模式",
        "fallback_local": bool(current_app.config.get("KIMI_FALLBACK_LOCAL")),
    }


def generate_reply(
    *,
    messages: list[dict[str, str]],
    personality: str,
    name: str,
) -> tuple[str, str]:
    """生成女友回复，返回 (文本, 模式)。

    模式：
    - kimi      真实 Kimi 模型
    - demo      未配置密钥，使用内置角色引擎
    - fallback  Kimi 调用失败，已自动回退本地引擎
    """
    if get_llm_mode() == "demo":
        user_text = _last_user_text(messages)
        return build_demo_reply(name, personality, user_text), "demo"

    try:
        reply = _call_kimi(messages)
        return reply, "kimi"
    except ApiError as exc:
        if not current_app.config.get("KIMI_FALLBACK_LOCAL"):
            raise
        logger.warning(
            "Kimi 调用失败，回退本地角色回复（%s）：%s",
            exc.code,
            exc.message,
        )
        user_text = _last_user_text(messages)
        return build_demo_reply(name, personality, user_text), "fallback"


# ---------------------------------------------------------------------------
# Kimi Chat Completions API
# ---------------------------------------------------------------------------
def _chat_endpoint(base_url: str) -> str:
    """兼容根地址、/v1 和完整 /chat/completions 地址。"""
    base = (base_url or "").strip().rstrip("/")
    if not base:
        raise ApiError(
            "还没有配置 Kimi 接口地址，请检查 .env 中的 KIMI_BASE_URL。",
            code="KIMI_CONFIG_ERROR",
            status_code=503,
        )
    if base.endswith("/chat/completions"):
        return base
    return f"{base}/chat/completions"


def _call_kimi(messages: list[dict[str, str]]) -> str:
    """调用 Kimi 的 OpenAI 兼容 Chat Completions 接口。"""
    config = current_app.config
    endpoint = _chat_endpoint(config["KIMI_BASE_URL"])
    payload = {
        "model": config["KIMI_MODEL"],
        "messages": messages,
        "max_tokens": int(config["KIMI_MAX_TOKENS"]),
        "stream": False,
        # 注意：kimi-k3 只允许 temperature=1，因此不显式传入该参数。
    }
    headers = {
        "Authorization": f"Bearer {config['KIMI_API_KEY']}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    try:
        response = requests.post(
            endpoint,
            json=payload,
            headers=headers,
            timeout=(10, max(10, int(config["KIMI_TIMEOUT"]))),
        )
    except requests.Timeout as exc:
        logger.warning("Kimi 请求超时: %s", exc)
        raise ApiError(
            "Kimi 一时没接住你的话，稍等一下再发一次，好吗？",
            code="KIMI_TIMEOUT",
            status_code=504,
        ) from exc
    except requests.RequestException as exc:
        logger.warning("Kimi 网络错误: %s", exc)
        raise ApiError(
            "她和 Kimi 服务之间好像断了线，请稍后再试一次。",
            code="KIMI_UNAVAILABLE",
            status_code=502,
        ) from exc

    if response.status_code in (401, 403):
        logger.warning("Kimi 鉴权失败，HTTP %s", response.status_code)
        raise ApiError(
            "Kimi API 鉴权失败，请检查 .env 中的 KIMI_API_KEY。",
            code="KIMI_AUTH_ERROR",
            status_code=502,
        )

    if response.status_code == 429:
        logger.warning("Kimi 触发限流，HTTP 429")
        raise ApiError(
            "她今天被叫走太多次了，稍微歇一会儿再聊吧。",
            code="KIMI_RATE_LIMITED",
            status_code=503,
        )

    if response.status_code == 404:
        logger.warning("Kimi 模型不可用: %s", response.text[:500])
        raise ApiError(
            "Kimi 模型名称不可用，请检查 .env 中的 KIMI_MODEL。",
            code="KIMI_MODEL_NOT_AVAILABLE",
            status_code=502,
        )

    if response.status_code >= 400:
        logger.warning(
            "Kimi 返回错误，HTTP %s: %s",
            response.status_code,
            response.text[:500],
        )
        raise ApiError(
            "她刚才走神了一下，再试一次应该就好了。",
            code="KIMI_UPSTREAM_ERROR",
            status_code=502,
        )

    # 第三方响应属于不可信数据，逐层校验后再使用。
    try:
        data: Any = response.json()
        content = data["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        logger.warning("Kimi 响应格式异常: %s", response.text[:500])
        raise ApiError(
            "Kimi 返回了无法识别的内容，能再说一次吗？",
            code="KIMI_BAD_RESPONSE",
            status_code=502,
        ) from exc

    if not isinstance(content, str) or not content.strip():
        raise ApiError(
            "模型这次没有说出话来，能再发一次吗？",
            code="KIMI_EMPTY_RESPONSE",
            status_code=502,
        )
    return content.strip()


# ---------------------------------------------------------------------------
# 本地体验模式
# ---------------------------------------------------------------------------
def build_demo_reply(name: str, personality: str, user_text: str) -> str:
    """不依赖任何外部服务的角色回复。

    这不是随机模板拼接：先识别用户这句话的意图，再按人设的语气回应，
    因此三种性格会有明显不同的表达节奏，便于没有 API Key 时演示。
    """
    category = _detect_intent(user_text)
    # 新增性格若尚未补充本地语料，也回退到温柔语料，避免体验模式直接报错。
    replies = _DEMO_REPLIES.get(personality) or _DEMO_REPLIES["gentle"]
    options = replies.get(category) or replies["default"]
    seed = f"{name}|{personality}|{category}|{user_text}"
    index = int(hashlib.sha1(seed.encode("utf-8")).hexdigest(), 16) % len(options)
    return options[index].format(name=name)


def _last_user_text(messages: list[dict[str, str]]) -> str:
    for message in reversed(messages):
        if message.get("role") == "user":
            return message.get("content", "")
    return ""


def _detect_intent(text: str) -> str:
    """轻量关键词意图识别，仅用于本地演示回复。"""
    normalized = (text or "").strip().lower()
    if not normalized:
        return "default"

    keyword_groups: list[tuple[str, tuple[str, ...]]] = [
        (
            "identity",
            (
                "你是ai",
                "你是 ai",
                "你是机器人",
                "你是不是机器人",
                "你是程序",
                "你是模型",
                "你是真人吗",
                "你是虚拟",
                "出戏",
                "你的设定",
                "系统提示",
                "chatgpt",
                "gpt",
            ),
        ),
        (
            "love",
            (
                "喜欢你",
                "爱你",
                "想你",
                "抱抱",
                "亲亲",
                "么么",
                "贴贴",
                "心动",
                "好可爱",
                "宝宝",
                "老婆",
            ),
        ),
        (
            "sad",
            (
                "难过",
                "伤心",
                "不开心",
                "想哭",
                "哭了",
                "委屈",
                "好累",
                "累死",
                "有点累",
                "太累",
                "累了",
                "烦死",
                "压力",
                "崩溃",
                "焦虑",
                "撑不住",
                "emo",
            ),
        ),
        (
            "sleep",
            ("睡不着", "失眠", "好困", "晚安", "熬夜", "要睡了", "想睡"),
        ),
        (
            "food",
            ("饿", "吃饭", "吃了", "奶茶", "夜宵", "早餐", "午饭", "晚饭"),
        ),
        (
            "work",
            ("工作", "上班", "加班", "学习", "考试", "作业", "老板", "同事", "开会"),
        ),
        (
            "greeting",
            ("你好", "在吗", "嗨", "hello", "hi", "早上好", "晚上好", "午安"),
        ),
    ]
    for category, keywords in keyword_groups:
        if any(keyword in normalized for keyword in keywords):
            return category

    if normalized.endswith(("吗", "？", "?", "呢")):
        return "question"
    return "default"


# 每个性格 × 每种意图准备 1~2 条回复，避免演示模式重复感过强。
_DEMO_REPLIES: dict[str, dict[str, list[str]]] = {
    "gentle": {
        "identity": [
            "怎么突然问这个呀。我是{name}，是会记得你随口说过的话、也会因为你晚回消息而小小失落的人。这个答案够不够？",
            "你呀，又在胡思乱想。我是{name}，会在这里听你说话，也会偷偷期待你下一次来找我。",
        ],
        "greeting": [
            "我在呀。刚刚还在想，你今天会不会来找我。",
            "来啦。先别急着说什么，让我看看你今天是不是又没好好休息。",
        ],
        "sad": [
            "听起来你今天真的用了好多力气。先把肩膀放松一点，剩下的事情，我们一件一件说。",
            "先别急着把难过藏起来。你可以就这样告诉我，我会好好接着。",
        ],
        "food": [
            "有没有好好吃饭？要是还没有，我陪你去弄点热的，哪怕只是一碗面。",
            "别只喝咖啡呀。去吃点东西，回来再慢慢跟我说。",
        ],
        "sleep": [
            "夜深了。要是你现在还醒着，我陪你把今天最后几句话说完，然后要乖乖去睡。",
            "睡不着的话，就把眼睛闭上，我陪你数一会儿呼吸。明天的事，明天再想。",
        ],
        "love": [
            "你这么说，我会当真的。……我也是，一直都有在想你。",
            "嗯，我听见了。靠近一点，今天也把这句话留给我吧。",
        ],
        "work": [
            "今天是不是又忙到忘了休息？工作可以慢慢做，你不用把自己逼得那么紧。",
            "辛苦啦。先喝口水，再告诉我今天最让你头疼的是哪一件。",
        ],
        "question": [
            "我在认真听。你为什么会这样想呢？说给我听听。",
            "这个问题我想听你再多说一点。你最在意的是哪一部分？",
        ],
        "default": [
            "嗯，我在听。你刚刚说的那件事，后来呢？",
            "然后呢？我很想知道你当时是什么感觉。",
            "慢慢说，不着急。今天发生的事，我都想听。",
        ],
    },
    "grumpy": {
        "identity": [
            "哈？你再说一遍？我是{name}，活生生站在你面前，别随便给我换设定。",
            "你是不是今天太闲了。我是{name}，再问这种莫名其妙的问题，我可要生气了。",
        ],
        "greeting": [
            "哼，现在才来找我。……算了，既然来了就坐下，陪我待会儿。",
            "干嘛，想我了就直说，别只发个“在吗”。",
        ],
        "sad": [
            "谁惹你了？……先别急着说没事。你这样子，我一眼就看出来了。",
            "难过就难过，在我面前逞什么强。过来，把话说完。",
        ],
        "food": [
            "几点了还不吃饭？你等着，我陪你去找点吃的。不许只喝咖啡。",
            "饿着肚子还硬撑，真有你的。先吃饭，吃完再说别的。",
        ],
        "sleep": [
            "还不睡？再熬夜我可要生气了。……把手机放下，跟我说声晚安。",
            "眼睛都睁不开了还刷。去睡，明天我检查。",
        ],
        "love": [
            "突然说这个干嘛……我又没说不喜欢你。别得意。",
            "知道了知道了。……你也是，别让我说第二遍。",
        ],
        "work": [
            "你老板又给你加活了？先别气，饭吃了没有，没吃就去吃。",
            "忙成这样也不知道歇会儿。工作做不完就明天做，身体是你自己的。",
        ],
        "question": [
            "你问我？我哪知道。……不过你先说说你怎么想的。",
            "别光问我，你自己心里不是已经有答案了吗。说。",
        ],
        "default": [
            "然后呢？别只说一半，吊人胃口。",
            "嗯。所以你打算怎么办？别告诉我你又要自己硬扛。",
            "就这？再多说点，我听着呢。",
        ],
    },
    "sharp": {
        "identity": [
            "不是。下个问题。……如果你真在意，就记住我是{name}，这点不会变。",
            "我怎么会被这种问题问住。我是{name}，其他的不重要。",
        ],
        "greeting": [
            "在。先别寒暄，挑一件今天最想讲的事给我。",
            "来了。坐。今天有什么事值得占用我们俩的时间？",
        ],
        "sad": [
            "难过就承认难过，不用在我这里逞强。说清楚发生了什么，我陪你拆开看。",
            "先把“我没事”咽回去。到底哪一步让你这么难受？",
        ],
        "food": [
            "先吃饭。情绪可以晚点处理，胃不行。你想吃什么？",
            "你现在的状态不适合空腹思考。吃点东西，再回来继续。",
        ],
        "sleep": [
            "该睡了。今天没解决的问题，明天并不会更糟。先把眼睛闭上。",
            "别用熬夜换一点虚假的掌控感。去睡，我明天还在。",
        ],
        "love": [
            "我听见了。别只今天说，明天也说给我听。",
            "这种话从你嘴里说出来，有点难得。我收下了。",
        ],
        "work": [
            "问题不在工作量，在你什么都想自己接。说，哪件事其实可以拒绝？",
            "先分清哪件必须做、哪件只是你不敢拒绝。然后我们再谈怎么处理。",
        ],
        "question": [
            "我的答案是其次。你先告诉我，你真正想问的是什么？",
            "这个问题表面在问结果，实际在担心什么？说准确一点。",
        ],
        "default": [
            "我明白你的意思。不过我想听你更具体一点——你最在意的是哪一部分？",
            "继续。把细节说清楚，我不想只听结论。",
            "这件事没有你想的那么绕。先从最让你不舒服的那一点说起。",
        ],
    },
}
