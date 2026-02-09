import contextlib
from re import Match
from typing import ClassVar
from datetime import datetime

from ..base import (
    BaseParser,
    handle,
)
from ..data import Platform, MediaContent
from .utils import get_post
from ...constants import PlatformEnum


class TiebaParser(BaseParser):
    platform: ClassVar[Platform] = Platform(
        name=PlatformEnum.TIEBA, display_name="百度贴吧"
    )

    @handle("tieba.baidu.com", r"tieba\.baidu\.com/p/(?P<post_id>\d+)")
    async def _parse(self, searched: Match[str]):
        # TODO: 显示吧头像
        post_id = searched.group("post_id")

        posts = await get_post(int(post_id))

        # 提取主题帖信息
        thread = posts.thread
        forum = posts.forum

        # 提取作者信息
        author = self.create_author(
            name=thread.user.show_name,
            avatar_url=f"http://tb.himg.baidu.com/sys/portraith/item/{thread.user.portrait}",
        )

        # 主楼正文内容
        contents: list[MediaContent] = []
        text_parts = [thread.title, "\n"]

        # 提取帖子正文
        if posts and posts.objs:
            main_post = posts.objs[0]
            # 处理文本内容
            text_parts.append(main_post.text)
            # 处理图片内容
            contents.extend(
                self.create_graphics_content(image_url=image.origin_src)
                for image in main_post.contents.imgs
            )
        # 处理评论
        comments = []
        if posts and posts.objs:
            # 获取前10条评论（优先显示楼主的评论）
            main_author_id = thread.user.user_id
            main_comments = []
            other_comments = []

            for post in posts.objs[1:]:  # 跳过主楼
                if post.user.user_id == main_author_id:
                    main_comments.append(post)
                else:
                    other_comments.append(post)

            # 合并评论，优先显示楼主的评论
            combined_comments = main_comments[:5] + other_comments[:5]

            for post in combined_comments:
                # 处理评论作者信息
                comment_author = {
                    "name": post.user.show_name,
                    "avatar": f"http://tb.himg.baidu.com/sys/portraith/item/{post.user.portrait}",
                }

                # 处理评论内容
                comment_content = post.text

                # 处理评论时间
                formatted_time = ""
                if hasattr(post, "create_time") and post.create_time:
                    with contextlib.suppress(Exception):
                        dt = datetime.fromtimestamp(post.create_time)
                        formatted_time = dt.strftime("%Y-%m-%d %H:%M")
                # 处理楼中楼评论
                child_posts = []
                if hasattr(post, "comments") and post.comments:
                    for comment in post.comments[:3]:  # 每个评论最多显示3条楼中楼
                        child_author = {
                            "name": comment.user.show_name,
                            "avatar": f"http://tb.himg.baidu.com/sys/portraith/item/{comment.user.portrait}",
                        }

                        child_content = comment.text

                        child_formatted_time = ""
                        if hasattr(comment, "create_time") and comment.create_time:
                            with contextlib.suppress(Exception):
                                dt = datetime.fromtimestamp(comment.create_time)
                                child_formatted_time = dt.strftime("%Y-%m-%d %H:%M")
                        child_posts.append(
                            {
                                "author": child_author,
                                "content": child_content,
                                "formatted_time": child_formatted_time,
                                "ups": comment.agree,
                            }
                        )

                comments.append(
                    {
                        "author": comment_author,
                        "content": comment_content,
                        "formatted_time": formatted_time,
                        "ups": post.agree,
                        "comments": len(child_posts),
                        "child_posts": child_posts,
                    }
                )

        extra = {
            "forum": {
                "name": forum.fname,
            },
            "comments": comments,
        }

        return self.result(
            title=thread.title,
            text="".join(text_parts),
            author=author,
            contents=contents, # TODO: 富文本
            timestamp=thread.create_time,
            url=f"https://tieba.baidu.com/p/{post_id}",
            extra=extra,
        )
