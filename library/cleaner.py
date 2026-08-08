from __future__ import annotations

import hashlib
import re
from html.parser import HTMLParser
from typing import Iterable, Mapping

CHAPTER_RE = re.compile(r"(?:第\s*[0-9一二三四五六七八九十百千]+\s*[章节回]|序章|番外|终章)", re.I)
SKIP_TAGS = {"script", "style", "nav", "form", "button", "noscript"}
SKIP_CLASSES = {"jammer", "sign", "pstatus", "replybtn", "fastpost", "ad"}


class _TextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip = 0
        self._skip_stack: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_map = dict(attrs)
        classes = set((attrs_map.get("class") or "").split())
        style = (attrs_map.get("style") or "").replace(" ", "").lower()
        if tag in SKIP_TAGS or classes.intersection(SKIP_CLASSES) or "display:none" in style:
            self._skip_stack.append(tag); self.skip = len(self._skip_stack)
        if not self.skip and tag in {"br", "p", "div", "section", "article", "tr", "li"}: self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self._skip_stack:
            for index in range(len(self._skip_stack) - 1, -1, -1):
                if self._skip_stack[index] == tag:
                    del self._skip_stack[index]; break
            self.skip = len(self._skip_stack)
        if not self.skip and tag in {"p", "div", "section", "article", "tr", "li"}: self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.skip: self.parts.append(data)


def clean_text(raw_html: str) -> str:
    # Discuz quote blocks may contain nested/malformed markup; remove their contents
    # before feeding the remaining document to the lightweight parser.
    raw_html = re.sub(r"<blockquote\b[^>]*>.*?</blockquote\s*>", "", raw_html, flags=re.I | re.S)
    parser = _TextParser(); parser.feed(raw_html)
    text = parser.get_data() if hasattr(parser, "get_data") else "".join(parser.parts)
    text = text.replace("\u200b", "").replace("\xa0", " ")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines()]
    result: list[str] = []
    blank = 0
    for line in lines:
        if not line:
            blank += 1
            if blank <= 1: result.append("")
        else:
            blank = 0; result.append(line)
    return "\n".join(result).strip()


def classify_post(cleaned: str, *, floor_number: int, has_image: bool = False, minimum_length: int = 200) -> str:
    if floor_number <= 1: return "正文"
    paragraphs = [x for x in re.split(r"\n\s*\n", cleaned) if x.strip()]
    if len(cleaned) >= minimum_length or CHAPTER_RE.search(cleaned) or len(paragraphs) >= 2 or has_image: return "正文"
    return "作者短回复"


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def clean_posts(posts: Iterable[Mapping[str, object]], *, minimum_length: int = 200) -> tuple[list[dict[str, object]], str]:
    cleaned_posts: list[dict[str, object]] = []
    for index, post in enumerate(posts, start=1):
        raw = str(post.get("raw_html") or "")
        text = clean_text(raw)
        item = dict(post); item["floor_number"] = int(post.get("floor_number") or index); item["clean_text"] = text
        item["post_type"] = classify_post(text, floor_number=int(item["floor_number"]), has_image="<img" in raw.lower(), minimum_length=minimum_length)
        item["content_hash"] = content_hash(text); cleaned_posts.append(item)
    novel = [str(p["clean_text"]) for p in cleaned_posts if p["post_type"] in {"正文", "作者说明"}]
    return cleaned_posts, content_hash("\n\n".join(novel))
