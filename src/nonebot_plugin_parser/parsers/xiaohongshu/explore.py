from msgspec import Struct, field
from msgspec.json import Decoder

from .common import Video, get_note_no_water_img


class Image(Struct):
    urlDefault: str


class User(Struct):
    nickname: str
    avatar: str


class NoteDetail(Struct):
    type: str
    title: str
    desc: str
    user: User
    lastUpdateTime: int
    imageList: list[Image] = field(default_factory=list)
    video: Video | None = None

    @property
    def nickname(self) -> str:
        return self.user.nickname

    @property
    def avatar_url(self) -> str:
        return self.user.avatar

    @property
    def image_urls(self) -> list[str]:
        return [get_note_no_water_img(item.urlDefault) for item in self.imageList]

    @property
    def video_url(self) -> str | None:
        return None if self.type != "video" or not self.video else self.video.video_url


class NoteDetailWrapper(Struct):
    """Wrapper for note detail, represents the value in noteDetailMap[xhs_id]"""

    note: NoteDetail


class Note(Struct):
    """Top-level note container with noteDetailMap"""

    noteDetailMap: dict[str, NoteDetailWrapper]


class InitialState(Struct):
    """Root structure of window.__INITIAL_STATE__"""

    note: Note


decoder = Decoder(InitialState)
