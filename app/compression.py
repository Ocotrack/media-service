import io
import os
import subprocess
from typing import Tuple
from PIL import Image

# -------- Images --------

def compress_image_aggressive(raw: bytes) -> Tuple[bytes, str, str]:
    """
    Aggressively compress image to WEBP.
    - Resize if larger than 1280px on any side.
    - Use lower quality (around 60).
    Returns: (compressed_bytes, content_type, extension)
    """
    image = Image.open(io.BytesIO(raw))

    if image.mode in ("RGBA", "P"):
        image = image.convert("RGB")

    max_size = 1280
    w, h = image.size
    if max(w, h) > max_size:
        if w >= h:
            new_w = max_size
            new_h = int(h * (max_size / w))
        else:
            new_h = max_size
            new_w = int(w * (max_size / h))
        image = image.resize((new_w, new_h), Image.LANCZOS)

    buf = io.BytesIO()
    image.save(
        buf,
        format="WEBP",
        quality=60,
        method=6,
    )
    buf.seek(0)
    return buf.read(), "image/webp", "webp"

# -------- Videos --------

def compress_video_ffmpeg(input_path: str, output_path: str) -> Tuple[str, str]:
    """
    Compress video aggressively using ffmpeg.
    - Scale down to max 720p.
    - Use H.264 with high CRF for strong compression.
    - AAC audio with low bitrate.
    Returns: (output_path, content_type)
    """
    cmd = [
        "ffmpeg",
        "-y",
        "-i", input_path,
        "-vf", "scale='min(1280,iw)':-2",
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "30",
        "-c:a", "aac",
        "-b:a", "96k",
        "-movflags", "+faststart",
        output_path,
    ]

    completed = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if completed.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {completed.stderr.decode(errors='ignore')}")

    return output_path, "video/mp4"
