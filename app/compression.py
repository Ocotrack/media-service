import io
import os
import asyncio
import logging
from typing import Tuple
from PIL import Image

from .config import IMAGE_MAX_DIMENSION, IMAGE_QUALITY

logger = logging.getLogger(__name__)


# ==============================
# Image Compression (Synchronous)
# ==============================

def compress_image(raw: bytes) -> Tuple[bytes, str, str]:
    """
    Compress an image to WebP format.
    - Resizes proportionally if any side exceeds IMAGE_MAX_DIMENSION px.
    - Quality is controlled by IMAGE_QUALITY (.env configurable).

    Returns: (compressed_bytes, content_type, file_extension)
    """
    image = Image.open(io.BytesIO(raw))

    # Convert Palette mode to RGBA to preserve transparency before saving as WebP.
    # WebP supports alpha natively, so RGBA images are saved directly without conversion.
    if image.mode == "P":
        image = image.convert("RGBA")

    w, h = image.size
    max_dim = IMAGE_MAX_DIMENSION
    if max(w, h) > max_dim:
        if w >= h:
            new_size = (max_dim, int(h * (max_dim / w)))
        else:
            new_size = (int(w * (max_dim / h)), max_dim)
        image = image.resize(new_size, Image.LANCZOS)

    buf = io.BytesIO()
    image.save(buf, format="WEBP", quality=IMAGE_QUALITY, method=6)
    buf.seek(0)

    return buf.read(), "image/webp", "webp"


# ==============================
# Video Compression (Asynchronous)
# ==============================

async def compress_video_async(input_path: str, output_path: str) -> None:
    """
    Compress a video to H.264 MP4 using FFmpeg.
    - Scales down to a maximum of 1280px width while keeping aspect ratio.
    - Uses 'veryfast' preset and CRF 28 for a balance of speed and quality.
    - AAC audio at 128k bitrate.
    - faststart flag for web streaming compatibility.

    Raises RuntimeError if ffmpeg exits with a non-zero return code.
    """
    cmd = [
        "ffmpeg",
        "-y",                          # Overwrite output without prompting
        "-i", input_path,
        "-vf", "scale='min(1280,iw)':-2",
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "28",
        "-c:a", "aac",
        "-b:a", "128k",
        "-movflags", "+faststart",
        output_path,
    ]

    logger.info("Starting FFmpeg compression: %s -> %s", input_path, output_path)

    # Non-blocking subprocess: does not hold the asyncio event loop
    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await process.communicate()

    if process.returncode != 0:
        error_msg = stderr.decode(errors="ignore")
        logger.error("FFmpeg failed (code %d): %s", process.returncode, error_msg)
        raise RuntimeError(f"FFmpeg compression failed: {error_msg[:500]}")

    logger.info("FFmpeg compression successful: %s", output_path)
