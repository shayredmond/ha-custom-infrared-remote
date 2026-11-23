"""Drawn remotes for the setup wizard.

The wizard dialogs are standard Home Assistant flows, which can show
markdown images. This module draws a remote as SVG, with the button to
press highlighted and the learned ones ticked, and serves it from a small
view so the dialog can show it with an image link.
"""

from dataclasses import dataclass
from html import escape
from typing import Literal

from aiohttp import web
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.http import HomeAssistantView

from .const import DOMAIN
from .templates import TEMPLATES

URL = f"/api/{DOMAIN}/remote"
DATA_VIEW = f"{DOMAIN}_view"

BODY = "#2c3136"
EDGE = "#1b1f22"
KEY = "#4a5157"
TEXT = "#eef1f3"
CURRENT = "#03a9f4"
DONE = "#2e9d4f"


@dataclass(frozen=True, slots=True)
class Key:
    """A button drawn on the remote."""

    x: float
    y: float
    w: float
    h: float
    label: str
    shape: Literal["round", "pill", "rect"] = "pill"


MEDIA: dict[str, Key] = {
    "power": Key(90, 44, 28, 28, "", "round"),
    "power_on": Key(54, 44, 26, 14, "ON"),
    "power_off": Key(126, 44, 26, 14, "OFF"),
    "input": Key(90, 76, 46, 14, "INPUT"),
    "source_hdmi_1": Key(54, 104, 20, 14, "1"),
    "source_hdmi_2": Key(78, 104, 20, 14, "2"),
    "source_hdmi_3": Key(102, 104, 20, 14, "3"),
    "source_hdmi_4": Key(126, 104, 20, 14, "4"),
    "up": Key(90, 142, 26, 18, "▲", "rect"),
    "left": Key(62, 170, 22, 22, "◀", "rect"),
    "ok": Key(90, 170, 24, 24, "OK", "round"),
    "right": Key(118, 170, 22, 22, "▶", "rect"),
    "down": Key(90, 198, 26, 18, "▼", "rect"),
    "home": Key(60, 226, 30, 14, "HOME"),
    "back": Key(120, 226, 30, 14, "BACK"),
    "volume_up": Key(58, 262, 24, 24, "+", "rect"),
    "volume_down": Key(58, 304, 24, 24, "−", "rect"),
    "mute": Key(90, 283, 24, 24, "MUTE", "round"),
    "channel_up": Key(122, 262, 24, 24, "+", "rect"),
    "channel_down": Key(122, 304, 24, 24, "−", "rect"),
    "previous": Key(54, 342, 22, 16, "◀◀"),
    "play": Key(78, 342, 22, 16, "▶"),
    "pause": Key(102, 342, 22, 16, "❚❚"),
    "next": Key(126, 342, 22, 16, "▶▶"),
    "stop": Key(72, 368, 22, 16, "■"),
    "play_pause": Key(108, 368, 30, 16, "▶❚❚"),
}
MEDIA_CAPTIONS = [(90, 94, "HDMI"), (58, 287, "VOL"), (122, 287, "CH")]

FAN: dict[str, Key] = {
    "power": Key(90, 46, 30, 30, "", "round"),
    "power_on": Key(56, 84, 26, 14, "ON"),
    "power_off": Key(124, 84, 26, 14, "OFF"),
    "speed_up": Key(66, 122, 26, 26, "+", "rect"),
    "speed_down": Key(66, 166, 26, 26, "−", "rect"),
    "oscillate": Key(114, 144, 28, 28, "OSC", "round"),
    "mode": Key(68, 206, 34, 14, "MODE"),
    "timer": Key(112, 206, 34, 14, "TIMER"),
}
FAN_CAPTIONS = [(66, 148, "SPEED")]

COVER: dict[str, Key] = {
    "open": Key(90, 56, 36, 28, "▲", "rect"),
    "stop": Key(90, 100, 36, 28, "■", "rect"),
    "close": Key(90, 144, 36, 28, "▼", "rect"),
}

LAYOUTS: dict[str, tuple[dict[str, Key], list[tuple[float, float, str]], int]] = {
    "tv": (MEDIA, MEDIA_CAPTIONS, 400),
    "projector": (MEDIA, MEDIA_CAPTIONS, 400),
    "speaker": (MEDIA, MEDIA_CAPTIONS, 400),
    "fan": (FAN, FAN_CAPTIONS, 240),
    "blinds": (COVER, [], 180),
    "screen": (COVER, [], 180),
}


def _power_icon(x: float, y: float, color: str) -> str:
    return (
        f'<path d="M{x - 5.5} {y - 4.5} a7 7 0 1 0 11 0" fill="none" '
        f'stroke="{color}" stroke-width="2" stroke-linecap="round"/>'
        f'<line x1="{x}" y1="{y - 8}" x2="{x}" y2="{y}" stroke="{color}" '
        'stroke-width="2" stroke-linecap="round"/>'
    )


def _key(key: Key, state: str) -> str:
    fill = {"current": CURRENT, "done": DONE}.get(state, KEY)
    opacity = 0.28 if state in ("unused", "skipped") else 1
    x, y, w, h = key.x - key.w / 2, key.y - key.h / 2, key.w, key.h
    radius = {"round": w / 2, "pill": h / 2, "rect": 5}[key.shape]
    parts = [f'<g opacity="{opacity}">']
    if state == "current":
        parts.append(
            f'<rect x="{x - 3}" y="{y - 3}" width="{w + 6}" height="{h + 6}" '
            f'rx="{radius + 3}" fill="none" stroke="{CURRENT}" stroke-width="2">'
            '<animate attributeName="opacity" values="1;0.15;1" dur="1.2s" '
            'repeatCount="indefinite"/></rect>'
        )
    parts.append(
        f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{radius}" fill="{fill}"/>'
    )
    if not key.label:
        parts.append(_power_icon(key.x, key.y + 1, TEXT))
    elif state == "done" and key.shape != "pill":
        parts.append(
            f'<path d="M{key.x - 5} {key.y} l3.5 3.5 l6.5 -7" fill="none" '
            f'stroke="{TEXT}" stroke-width="2" stroke-linecap="round" '
            'stroke-linejoin="round"/>'
        )
    else:
        size = 7 if len(key.label) > 2 else 10
        parts.append(
            f'<text x="{key.x}" y="{key.y}" fill="{TEXT}" font-size="{size}" '
            'font-family="Roboto, Helvetica, Arial, sans-serif" font-weight="600" '
            'text-anchor="middle" dominant-baseline="central">'
            f"{escape(key.label)}</text>"
        )
    parts.append("</g>")
    return "".join(parts)


def render_remote(
    device_type: str,
    current: str | None = None,
    done: frozenset[str] = frozenset(),
    skipped: frozenset[str] = frozenset(),
    queued: frozenset[str] = frozenset(),
    waiting: bool = False,
) -> str | None:
    """Return the SVG of a remote, or None for device types without one.

    Buttons not in `queued` and not learned are drawn faint, so the remote
    shows what this run of the wizard is about.
    """
    if device_type not in LAYOUTS:
        return None
    keys, captions, height = LAYOUTS[device_type]
    roles = {r.key for r in TEMPLATES[device_type].roles}
    width = 180
    body_w = 120 if keys is not COVER else 76
    body_x = (width - body_w) / 2

    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
        f'width="{width}" height="{height}" role="img">',
    ]
    if current and waiting:
        for i, r in enumerate((10, 18, 26)):
            out.append(
                f'<path d="M{width / 2 - r} {16 - i * 2} a{r} {r} 0 0 1 {2 * r} 0" '
                f'fill="none" stroke="{CURRENT}" stroke-width="2" '
                'stroke-linecap="round" opacity="0">'
                f'<animate attributeName="opacity" values="0;1;0" dur="1.2s" '
                f'begin="{i * 0.2}s" repeatCount="indefinite"/></path>'
            )
    out.append(
        f'<rect x="{body_x}" y="22" width="{body_w}" height="{height - 30}" '
        f'rx="26" fill="{BODY}" stroke="{EDGE}" stroke-width="2"/>'
    )
    for x, y, label in captions:
        out.append(
            f'<text x="{x}" y="{y}" fill="#9aa3aa" font-size="6.5" '
            'font-family="Roboto, Helvetica, Arial, sans-serif" font-weight="600" '
            f'text-anchor="middle" dominant-baseline="central">{label}</text>'
        )
    for role, key in keys.items():
        if role not in roles:
            continue
        if role == current:
            state = "current"
        elif role in done:
            state = "done"
        elif role in skipped:
            state = "skipped"
        elif role in queued:
            state = "queued"
        else:
            state = "unused"
        out.append(_key(key, state))
    out.append("</svg>")
    return "".join(out)


def image_url(
    device_type: str,
    current: str | None = None,
    done: set[str] | None = None,
    skipped: set[str] | None = None,
    queued: list[str] | None = None,
    waiting: bool = False,
) -> str:
    """Return the URL of a drawn remote for a markdown image."""
    params = [f"current={current or ''}", f"waiting={int(waiting)}"]
    params.append("done=" + ",".join(sorted(done or ())))
    params.append("skipped=" + ",".join(sorted(skipped or ())))
    params.append("queued=" + ",".join(queued or ()))
    return f"{URL}/{device_type}.svg?" + "&".join(params)


class RemoteImageView(HomeAssistantView):
    """Serve the drawn remotes.

    No authentication: an img tag can't send a token, and the image only
    draws fixed button layouts from the query string, nothing from the user.
    """

    url = URL + "/{device_type}.svg"
    name = f"api:{DOMAIN}:remote"
    requires_auth = False

    async def get(self, request: web.Request, device_type: str) -> web.Response:
        """Return the SVG."""

        def roles(name: str) -> frozenset[str]:
            return frozenset(filter(None, request.query.get(name, "").split(",")))

        svg = render_remote(
            device_type,
            request.query.get("current") or None,
            roles("done"),
            roles("skipped"),
            roles("queued"),
            request.query.get("waiting") == "1",
        )
        if svg is None:
            return web.Response(status=404)
        return web.Response(
            text=svg,
            content_type="image/svg+xml",
            headers={"Cache-Control": "public, max-age=86400"},
        )


@callback
def async_register_view(hass: HomeAssistant) -> None:
    """Register the image view once."""
    if hass.data.get(DATA_VIEW):
        return
    hass.http.register_view(RemoteImageView())
    hass.data[DATA_VIEW] = True
