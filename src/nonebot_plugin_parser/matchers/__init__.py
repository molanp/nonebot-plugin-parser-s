import re
from typing import TypeVar

from nonebot import logger, get_driver, on_command
from nonebot.params import CommandArg
from nonebot.adapters import Message

from .rule import SUPER_PRIVATE, Searched, SearchResult, on_keyword_regex
from ..utils import LimitedSizeDict
from ..config import pconfig
from ..helper import UniHelper, UniMessage
from ..parsers import BaseParser, ParseResult, BilibiliParser
from ..renders import get_renderer
from ..download import DOWNLOADER


def _get_enabled_parser_classes() -> list[type[BaseParser]]:
    disabled_platforms = set(pconfig.disabled_platforms)
    all_subclass = BaseParser.get_all_subclass()
    return [_cls for _cls in all_subclass if _cls.platform.name not in disabled_platforms]


# 关键词 -> Parser 映射
KEYWORD_PARSER_MAP: dict[str, BaseParser] = {}
T = TypeVar("T", bound=BaseParser)


def get_parser(keyword: str) -> BaseParser:
    return KEYWORD_PARSER_MAP[keyword]


def get_parser_by_type(parser_type: type[T]) -> T:
    for parser in KEYWORD_PARSER_MAP.values():
        if isinstance(parser, parser_type):
            return parser
    raise ValueError(f"未找到类型为 {parser_type} 的 parser 实例")


@get_driver().on_startup
def register_parser_matcher():
    enabled_classes = _get_enabled_parser_classes()

    enabled_platforms = []
    for _cls in enabled_classes:
        parser = _cls()
        enabled_platforms.append(parser.platform.display_name)
        for keyword, _ in _cls._key_patterns:
            KEYWORD_PARSER_MAP[keyword] = parser
    logger.info(f"启用平台: {', '.join(sorted(enabled_platforms))}")

    patterns = [p for _cls in enabled_classes for p in _cls._key_patterns]
    matcher = on_keyword_regex(*patterns)
    matcher.append_handler(parser_handler)


# 缓存结果
_RESULT_CACHE = LimitedSizeDict[str, ParseResult](max_size=50)
# 消息ID与解析结果的关联缓存，用于多用户场景
_MSG_ID_RESULT_MAP = LimitedSizeDict[str, ParseResult](max_size=100)


def clear_result_cache():
    _RESULT_CACHE.clear()
    _MSG_ID_RESULT_MAP.clear()


@UniHelper.with_reaction
async def parser_handler(
    sr: SearchResult = Searched(),
):
    """统一的解析处理器"""
    # 1. 获取缓存结果
    cache_key = sr.searched.group(0)
    result = _RESULT_CACHE.get(cache_key)

    if result is None:
        # 2. 获取对应平台 parser
        parser = get_parser(sr.keyword)
        result = await parser.parse(sr.keyword, sr.searched)
        logger.debug(f"解析结果: {result}")
    else:
        logger.debug(f"命中缓存: {cache_key}, 结果: {result}")

    # 3. 渲染内容消息并发送，保存消息ID
    renderer = get_renderer(result.platform.name)
    logger.debug(f"获取渲染器：{renderer}")
    try:
        async for message in renderer.render_messages(result):
            msg_sent = await message.send()
            # 保存消息ID与解析结果的关联
            if msg_sent:
                msg_id = None
                try:
                    # 处理Receipt对象的msg_ids属性
                    receipt_msg_ids = msg_sent.msg_ids
                    logger.debug(f"Receipt.msg_ids: {receipt_msg_ids}")
                    if receipt_msg_ids:
                        for msg_id_info in receipt_msg_ids:
                            if isinstance(msg_id_info, dict) and "message_id" in msg_id_info:
                                msg_id = str(msg_id_info["message_id"])
                                logger.debug(f"通过Receipt.msg_ids[0]['message_id']获取到消息ID: {msg_id}")
                                break
                    if msg_id:
                        _MSG_ID_RESULT_MAP[msg_id] = result
                        logger.debug(f"保存消息ID与解析结果的关联: msg_id={msg_id}, url={cache_key}")
                        logger.debug(f"当前_MSG_ID_RESULT_MAP大小: {len(_MSG_ID_RESULT_MAP)}")
                    else:
                        logger.debug("未获取到消息ID")
                except (NotImplementedError, TypeError, AttributeError) as e:
                    # 某些适配器可能不支持获取消息ID，忽略此错误
                    logger.debug(f"获取消息ID失败: {e}")
    except Exception as e:
        # 渲染失败时，尝试直接发送解析结果
        logger.error(f"渲染失败: {e}")
        # from ..helper import UniMessage
        # await UniMessage(f"解析成功，但渲染失败: {e!s}").send()

    # 4. 缓存解析结果
    _RESULT_CACHE[cache_key] = result


@on_command("bm", priority=3, block=True).handle()
@UniHelper.with_reaction
async def _(message: Message = CommandArg()):
    text = message.extract_plain_text()
    matched = re.search(r"(BV[A-Za-z0-9]{10})(\s\d{1,3})?", text)
    if not matched:
        await UniMessage("请发送正确的 BV 号").finish()

    bvid, page_num = matched[1], matched[2]
    page_idx = int(page_num) if page_num else 0

    parser = get_parser_by_type(BilibiliParser)

    _, audio_url = await parser.extract_download_urls(bvid=bvid, page_index=page_idx)
    if not audio_url:
        await UniMessage("未找到可下载的音频").finish()

    audio_path = await DOWNLOADER.download_audio(
        audio_url, audio_name=f"{bvid}-{page_idx}.mp3", ext_headers=parser.headers
    )
    await UniMessage(UniHelper.record_seg(audio_path)).send()

    if pconfig.need_upload:
        await UniMessage(UniHelper.file_seg(audio_path)).send()


from ..download import YTDLP_DOWNLOADER

if YTDLP_DOWNLOADER is not None:
    from ..parsers import YouTubeParser

    @on_command("ym", priority=3, block=True).handle()
    @UniHelper.with_reaction
    async def _(message: Message = CommandArg()):
        text = message.extract_plain_text()
        parser = get_parser_by_type(YouTubeParser)
        _, matched = parser.search_url(text)
        if not matched:
            await UniMessage("请发送正确的油管链接").finish()

        url = matched.group(0)

        audio_path = await YTDLP_DOWNLOADER.download_audio(url)
        await UniMessage(UniHelper.record_seg(audio_path)).send()

        if pconfig.need_upload:
            await UniMessage(UniHelper.file_seg(audio_path)).send()


@on_command("blogin", block=True, permission=SUPER_PRIVATE).handle()
async def _():
    parser = get_parser_by_type(BilibiliParser)
    qrcode = await parser.login_with_qrcode()
    await UniMessage(UniHelper.img_seg(raw=qrcode)).send()
    async for msg in parser.check_qr_state():
        await UniMessage(msg).send()
