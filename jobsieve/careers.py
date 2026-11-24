import ipaddress
import re
import socket
from urllib import robotparser
from urllib.parse import urljoin, urlsplit

import requests

from . import discovery
from .sources.base import CLIENT_USER_AGENT, HTTP_TIMEOUT_SECONDS

MAX_PAGE_BYTES = 3_000_000
URL_IN_TEXT = re.compile(r"https?://[^\s\"'<>)\\]+")


class CareerPageError(Exception):
    pass


def check_public_url(url: str) -> str:
    parts = urlsplit(str(url or "").strip())
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise CareerPageError("enter a full web address starting with http:// or https://")
    try:
        addresses = {info[4][0] for info in socket.getaddrinfo(parts.hostname, parts.port or 443)}
    except OSError as error:
        raise CareerPageError(f"cannot find {parts.hostname}") from error
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            raise CareerPageError("only public web addresses can be read")
    return parts.geturl()


def robots_allow(url: str) -> bool:
    parts = urlsplit(url)
    parser = robotparser.RobotFileParser()
    try:
        response = requests.get(
            f"{parts.scheme}://{parts.netloc}/robots.txt",
            timeout=HTTP_TIMEOUT_SECONDS,
            headers={"User-Agent": CLIENT_USER_AGENT},
        )
    except requests.RequestException:
        return True
    if response.status_code in (401, 403):
        return False
    if response.status_code >= 400:
        return True
    parser.parse(response.text.splitlines())
    return parser.can_fetch(CLIENT_USER_AGENT, url)


def boards_in_html(html: str) -> list[tuple[str, str]]:
    found = []
    for url in URL_IN_TEXT.findall(str(html or "").replace("\\/", "/")):
        board = discovery.board_from_url(url.rstrip(".,;"))
        if board and board not in found:
            found.append(board)
    return found


def read_page(url: str) -> str:
    current = url
    for _ in range(4):
        checked = check_public_url(current)
        if not robots_allow(checked):
            raise CareerPageError("that site's robots.txt does not allow automated reading of this page")
        try:
            response = requests.get(
                checked,
                timeout=HTTP_TIMEOUT_SECONDS,
                headers={"User-Agent": CLIENT_USER_AGENT},
                stream=True,
                allow_redirects=False,
            )
            if response.is_redirect and response.headers.get("Location"):
                current = urljoin(checked, response.headers["Location"])
                response.close()
                continue
            response.raise_for_status()
            body = response.raw.read(MAX_PAGE_BYTES + 1, decode_content=True)
        except requests.RequestException as error:
            raise CareerPageError(f"cannot read the page: {str(error)[:100]}") from error
        return body[:MAX_PAGE_BYTES].decode(response.encoding or "utf-8", errors="replace")
    raise CareerPageError("too many redirects")


def find_boards(url: str) -> list[tuple[str, str]]:
    host_board = discovery.board_from_url(url)
    if host_board:
        return [host_board]
    return boards_in_html(read_page(url))


def add_from_page(url: str) -> list[tuple[str, str, bool]]:
    from . import watchlist

    return [
        (board, slug, watchlist.add(board, slug, added_by="career page"))
        for board, slug in find_boards(url)
    ]
