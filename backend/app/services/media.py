"""Media validation, compression, and background processing.

Validate: sniff real MIME via filetype library; check size/duration caps.
Process (background): Pillow for images, ffmpeg for videos; upload display+thumb.

The processor opens its own committing session (no request session available in
the background task). Session comes from app.db.engine.SessionFactory.

TODO: move process_attachment into the real AnalysisQueue when it lands.
"""

import asyncio
import io
import json
import subprocess
import tempfile
import time
from pathlib import Path

import filetype  # type: ignore[import-untyped]
from fastapi import UploadFile

from app.core import storage
from app.core.config import settings
from app.models.attachment import Attachment
from app.schemas.forum import AttachmentOut
from app.services.exceptions import FileTooLargeError, UnsupportedMediaTypeError


def _sniff_mime(data: bytes) -> str | None:
    """Return real MIME type from file content; None if unrecognised."""
    kind = filetype.guess(data)
    return kind.mime if kind is not None else None


def attachment_out(a: Attachment) -> AttachmentOut:
    """ORM row -> wire shape, minting presigned URLs for whatever is ready.

    Lives here rather than in the forum service because attachments hang off
    posts, comments and messages alike; every one of those reads maps them the
    same way.
    """
    return AttachmentOut(
        id=a.id,
        media_type=a.media_type,
        status=a.status,
        mime=a.mime,
        width=a.width,
        height=a.height,
        duration_seconds=a.duration_seconds,
        display_url=storage.presigned_get_url(a.display_key) if a.display_key else None,
        thumbnail_url=(
            storage.presigned_get_url(a.thumbnail_key) if a.thumbnail_key else None
        ),
    )


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


async def validate_upload(file: UploadFile, data: bytes) -> tuple[str, str]:
    """Returns (media_type, real_mime) or raises a domain error."""
    real_mime = _sniff_mime(data)
    if real_mime is None:
        raise UnsupportedMediaTypeError("unrecognised file format")

    if real_mime in settings.allowed_image_mimes:
        if len(data) > settings.max_image_bytes:
            raise FileTooLargeError(
                f"image exceeds {settings.max_image_bytes // 1_000_000} MB limit"
            )
        return "image", real_mime

    if real_mime in settings.allowed_video_mimes:
        if len(data) > settings.max_video_bytes:
            raise FileTooLargeError(
                f"video exceeds {settings.max_video_bytes // 1_000_000} MB limit"
            )
        duration = await _probe_duration(data, real_mime)
        if duration is not None and duration > settings.max_video_duration_seconds:
            raise FileTooLargeError(
                f"video exceeds {settings.max_video_duration_seconds}s duration limit"
            )
        return "video", real_mime

    raise UnsupportedMediaTypeError(f"file type not allowed: {real_mime}")


async def _probe_duration(data: bytes, mime: str) -> float | None:
    """Run ffprobe to get video duration; returns None on failure."""
    ext = ".mp4" if "mp4" in mime else ".webm" if "webm" in mime else ".mov"
    with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as f:
        f.write(data)
        tmp_path = f.name
    try:
        result = await asyncio.to_thread(
            subprocess.run,
            ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", tmp_path],
            capture_output=True,
            timeout=30,
        )
        if result.returncode != 0:
            return None
        info = json.loads(result.stdout)
        raw = info.get("format", {}).get("duration", 0)
        return float(raw) or None
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None
    finally:
        Path(tmp_path).unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Background processing
# ---------------------------------------------------------------------------

_processor = None  # override in tests — must be an async callable or None


def set_processor(fn) -> None:  # type: ignore[type-arg]
    """Tests inject an async stub here; pass None to restore real processing."""
    global _processor
    _processor = fn


async def process_attachment(attachment_id: int) -> None:
    """Compress/transcode, upload derived objects, mark attachment ready.

    Opens its own committing session — runs outside the request session.
    """
    from app.db.engine import SessionFactory
    from app.db.repos import attachments as attachments_repo

    if _processor is not None:
        await _processor(attachment_id)
        return

    async with SessionFactory() as session:
        try:
            attachment = await attachments_repo.get(session, attachment_id)
            if attachment is None:
                return

            data = await storage.get_object(attachment.original_key)
            base_key = f"attachments/{attachment_id}"

            width: int | None
            height: int | None
            duration: float | None

            if attachment.media_type == "image":
                display_key, thumb_key, width, height = await _process_image(data, base_key)
                duration = None
            else:
                display_key, thumb_key, width, height, duration = await _process_video(
                    data, base_key, attachment.mime
                )

            await attachments_repo.set_ready(
                session,
                attachment_id,
                display_key=display_key,
                thumbnail_key=thumb_key,
                width=width,
                height=height,
                duration_seconds=duration,
            )
            await session.commit()
        except (OSError, ValueError, subprocess.SubprocessError, RuntimeError):
            try:
                await attachments_repo.set_failed(session, attachment_id)
                await session.commit()
            except (OSError, RuntimeError):
                pass


async def _process_image(data: bytes, base_key: str) -> tuple[str, str, int, int]:
    """Strip EXIF, downscale, encode to WebP. Returns (display_key, thumb_key, w, h)."""
    from PIL import ImageOps
    from PIL.Image import Image as PILImage
    from PIL.Image import Resampling
    from PIL.Image import open as pil_open

    def _compress() -> tuple[bytes, bytes, int, int]:
        raw = pil_open(io.BytesIO(data))
        img: PILImage = ImageOps.exif_transpose(raw) or raw
        if img.mode not in ("RGB", "RGBA"):
            img = img.convert("RGBA" if img.mode == "P" else "RGB")

        max_d = settings.image_max_dimension
        if img.width > max_d or img.height > max_d:
            img.thumbnail((max_d, max_d), Resampling.LANCZOS)

        display_buf, thumb_buf = io.BytesIO(), io.BytesIO()
        img.save(display_buf, format="WEBP", quality=82, method=4)
        thumb = img.copy()
        thumb.thumbnail((320, 320), Resampling.LANCZOS)
        thumb.save(thumb_buf, format="WEBP", quality=70, method=4)
        return display_buf.getvalue(), thumb_buf.getvalue(), img.width, img.height

    display_data, thumb_data, w, h = await asyncio.to_thread(_compress)
    display_key, thumb_key = f"{base_key}/display.webp", f"{base_key}/thumb.webp"
    await storage.put_object(display_key, display_data, "image/webp")
    await storage.put_object(thumb_key, thumb_data, "image/webp")
    return display_key, thumb_key, w, h


async def _process_video(
    data: bytes, base_key: str, mime: str
) -> tuple[str, str, int | None, int | None, float | None]:
    """Transcode to H.264/AAC MP4, extract poster frame."""
    ext = ".mp4" if "mp4" in mime else ".webm" if "webm" in mime else ".mov"
    max_h = settings.video_max_height

    def _transcode() -> tuple[bytes, bytes, int | None, int | None, float | None]:
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / f"input{ext}"
            dst = Path(tmp) / "display.mp4"
            thumb_dst = Path(tmp) / "thumb.jpg"
            src.write_bytes(data)

            subprocess.run(
                [
                    "ffmpeg", "-y", "-i", str(src),
                    "-vf", f"scale=-2:'min({max_h},ih)'",
                    "-c:v", "libx264", "-crf", "23", "-preset", "fast",
                    "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart",
                    str(dst),
                ],
                check=True, capture_output=True, timeout=300,
            )
            subprocess.run(
                ["ffmpeg", "-y", "-i", str(dst), "-ss", "1", "-frames:v", "1",
                 "-vf", "scale=320:-2", str(thumb_dst)],
                check=True, capture_output=True, timeout=30,
            )

            probe = subprocess.run(
                ["ffprobe", "-v", "quiet", "-print_format", "json",
                 "-show_streams", "-show_format", str(dst)],
                capture_output=True, timeout=30, check=False,
            )
            width = height = None
            duration: float | None = None
            if probe.returncode == 0:
                info = json.loads(probe.stdout)
                for s in info.get("streams", []):
                    if s.get("codec_type") == "video":
                        width, height = s.get("width"), s.get("height")
                if raw := info.get("format", {}).get("duration"):
                    duration = float(raw)

            return dst.read_bytes(), thumb_dst.read_bytes(), width, height, duration

    display_data, thumb_data, w, h, dur = await asyncio.to_thread(_transcode)
    display_key, thumb_key = f"{base_key}/display.mp4", f"{base_key}/thumb.jpg"
    await storage.put_object(display_key, display_data, "video/mp4")
    await storage.put_object(thumb_key, thumb_data, "image/jpeg")
    return display_key, thumb_key, w, h, dur


# ---------------------------------------------------------------------------
# Orphan sweep
# ---------------------------------------------------------------------------


async def sweep_orphans(older_than_seconds: float = 86400.0) -> int:
    """Delete unlinked attachments older than cutoff. Returns count deleted."""
    from sqlalchemy import delete as sa_delete

    from app.db import repos
    from app.db.engine import SessionFactory
    from app.models.attachment import Attachment

    cutoff = time.time() - older_than_seconds
    async with SessionFactory() as session:
        orphans = await repos.attachments.list_unlinked_before(session, cutoff)
        if not orphans:
            return 0
        keys = [
            k
            for a in orphans
            for k in [a.original_key, a.display_key, a.thumbnail_key]
            if k is not None
        ]
        await storage.delete_objects(keys)
        await session.execute(
            sa_delete(Attachment).where(Attachment.id.in_([a.id for a in orphans]))
        )
        await session.commit()
    return len(orphans)
