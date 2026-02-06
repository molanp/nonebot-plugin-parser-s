from typing import Any, Optional

from msgspec import Struct, convert


class AuthorInfo(Struct):
    """作者信息"""

    name: str
    face: str
    mid: int
    pub_time: str
    pub_ts: int
    views_text: str | None = None


class VideoArchive(Struct):
    """视频信息"""

    aid: str
    bvid: str
    title: str
    desc: str
    cover: str


class OpusImage(Struct):
    """图文动态图片信息"""

    url: str


class OpusSummary(Struct):
    """图文动态摘要"""

    text: str


class OpusContent(Struct):
    """图文动态内容"""

    jump_url: str
    pics: list[OpusImage]
    summary: OpusSummary
    title: str | None = None


class DynamicMajor(Struct):
    """动态主要内容 (Major)"""

    type: str | None = None
    archive: VideoArchive | None = None
    opus: OpusContent | None = None
    desc: OpusSummary | None = None
    draw: dict[str, Any] | None = None

    @property
    def title(self) -> str | None:
        """获取标题"""
        if self.type == "MAJOR_TYPE_ARCHIVE" and self.archive:
            return self.archive.title
        return None

    @property
    def text(self) -> str | None:
        """获取文本内容"""
        if self.type == "MAJOR_TYPE_ARCHIVE" and self.archive:
            return self.archive.desc
        elif self.type == "MAJOR_TYPE_OPUS" and self.opus:
            return self.opus.summary.text
        elif self.desc:
            return self.desc.text
        return None

    @property
    def image_urls(self) -> list[str]:
        """获取图片URL列表"""
        # 优先从opus获取图片
        if self.type == "MAJOR_TYPE_OPUS" and self.opus and self.opus.pics:
            return [pic.url for pic in self.opus.pics]
        # 从draw类型获取图片
        elif self.type == "MAJOR_TYPE_DRAW" and self.draw:
            pictures = self.draw.get("pictures", [])
            return [pic.get("img_src", "") for pic in pictures if pic.get("img_src")]
        # 从视频archive获取封面
        elif self.type == "MAJOR_TYPE_ARCHIVE" and self.archive and self.archive.cover:
            return [self.archive.cover]
        return []

    @property
    def cover_url(self) -> str | None:
        """获取封面URL"""
        if self.type == "MAJOR_TYPE_ARCHIVE" and self.archive:
            return self.archive.cover
        # 如果是图文动态，返回第一张图片作为封面
        image_urls = self.image_urls
        return image_urls[0] if image_urls else None


class DynamicModule(Struct):
    """动态模块"""

    module_author: AuthorInfo
    module_dynamic: dict[str, Any] | None = None
    module_stat: dict[str, Any] | None = None

    @property
    def author_name(self) -> str:
        """获取作者名称"""
        return self.module_author.name

    @property
    def author_face(self) -> str:
        """获取作者头像URL"""
        return self.module_author.face

    @property
    def pub_ts(self) -> int:
        """获取发布时间戳"""
        return self.module_author.pub_ts

    @property
    def major_info(self) -> dict[str, Any] | None:
        """获取主要内容信息"""
        if self.module_dynamic:
            if major := self.module_dynamic.get("major"):
                return major
            # 转发类型动态没有 major
            return self.module_dynamic
        return None


class DynamicInfo(Struct):
    """动态信息"""

    id_str: str
    type: str
    visible: bool
    modules: DynamicModule
    basic: dict[str, Any] | None = None
    # 【关键修改】添加 orig 字段以支持转发内容 (递归结构)
    orig: Optional["DynamicInfo"] = None

    @property
    def name(self) -> str:
        """获取作者名称"""
        return self.modules.author_name

    @property
    def avatar(self) -> str:
        """获取作者头像URL"""
        return self.modules.author_face

    @property
    def timestamp(self) -> int:
        """获取发布时间戳"""
        return self.modules.pub_ts

    @property
    def title(self) -> str | None:
        """获取标题"""
        if major_info := self.modules.major_info:
            major = convert(major_info, DynamicMajor)
            return major.title
        # 如果是转发动态且没有 major title，可以返回默认值
        return "转发动态" if self.type == "DYNAMIC_TYPE_FORWARD" else None

    @property
    def text(self) -> str | None:
        """获取文本内容"""
        # 【关键修改】优先从 modules.module_dynamic.desc.text 获取
        # 这是用户发布的文字（包括转发时的评论）
        if self.modules.module_dynamic:
            desc = self.modules.module_dynamic.get("desc")
            if desc and isinstance(desc, dict):
                if text_content := desc.get("text"):
                    return text_content

        if major_info := self.modules.major_info:
            major = convert(major_info, DynamicMajor)
            return major.text

        return None

    @property
    def image_urls(self) -> list[str]:
        """获取图片URL列表"""
        if major_info := self.modules.major_info:
            major = convert(major_info, DynamicMajor)
            if major_images := major.image_urls:
                return major_images

        # 2. 处理分享图片的动态，可能直接包含图片信息
        # 检查是否为图文动态类型
        if self.type == "DYNAMIC_TYPE_DRAW" and self.modules.module_dynamic:
            # 从module_dynamic中查找图片信息
            dynamic_data = self.modules.module_dynamic

            # 检查是否有pictures字段
            if isinstance(dynamic_data, dict):
                # 尝试从不同位置获取图片
                if "pics" in dynamic_data:
                    # 直接的pics字段
                    return [
                        pic.get("url", "")
                        for pic in dynamic_data["pics"]
                        if pic.get("url")
                    ]
                elif "major" in dynamic_data:
                    major = dynamic_data["major"]
                    if isinstance(major, dict):
                        # 检查major是否包含图片信息
                        if "pics" in major:
                            return [
                                pic.get("url", "")
                                for pic in major["pics"]
                                if pic.get("url")
                            ]
                        elif "draw" in major and isinstance(major["draw"], dict):
                            draw = major["draw"]
                            if "pictures" in draw:
                                return [
                                    pic.get("img_src", "")
                                    for pic in draw["pictures"]
                                    if pic.get("img_src")
                                ]

        # 3. 转发动态时，如果主体没有图片，不再从orig获取图片
        # 直接返回空列表，后续会使用默认图片
        return []

    @property
    def cover_url(self) -> str | None:
        """获取封面URL"""
        if major_info := self.modules.major_info:
            major = convert(major_info, DynamicMajor)
            if cover := major.cover_url:
                return cover

        # 2. 从图片列表中获取第一张作为封面
        image_urls = self.image_urls
        return image_urls[0] if image_urls else None


class DynamicData(Struct):
    """动态项目"""

    item: DynamicInfo
