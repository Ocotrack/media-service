import io
import os
import tempfile

from .queue import dequeue_job
from .config import minio_internal, MINIO_BUCKET
from .models import get_media_item, save_media
from .compression import compress_image_aggressive, compress_video_ffmpeg


def process_image_job(job):
    media_id = job["media_id"]
    original_path = job["original_path"]
    final_path = job["final_path"]

    item = get_media_item(media_id)
    if not item:
        print(f"[image] media_id {media_id} not found in Redis; skipping")
        return

    with tempfile.NamedTemporaryFile(delete=False) as tmp_in:
        minio_internal.fget_object(MINIO_BUCKET, original_path, tmp_in.name)
        tmp_in_path = tmp_in.name

    with open(tmp_in_path, "rb") as f:
        raw = f.read()
    try:
        compressed, new_type, ext = compress_image_aggressive(raw)
    finally:
        try:
            os.remove(tmp_in_path)
        except FileNotFoundError:
            pass

    minio_internal.put_object(
        MINIO_BUCKET,
        final_path,
        io.BytesIO(compressed),
        len(compressed),
        content_type=new_type,
    )

    try:
        minio_internal.remove_object(MINIO_BUCKET, original_path)
    except Exception as e:
        print(f"[image] warning removing original {original_path}: {e}")

    item.path = final_path
    item.content_type = new_type
    item.status = "ready"
    item.original_path = None
    save_media(item)
    print(f"[image] processed {media_id} -> {final_path}")


def process_video_job(job):
    media_id = job["media_id"]
    original_path = job["original_path"]
    final_path = job["final_path"]

    item = get_media_item(media_id)
    if not item:
        print(f"[video] media_id {media_id} not found in Redis; skipping")
        return

    with tempfile.NamedTemporaryFile(delete=False) as tmp_in, \
         tempfile.NamedTemporaryFile(delete=False, suffix=".mp4") as tmp_out:
        minio_internal.fget_object(MINIO_BUCKET, original_path, tmp_in.name)
        tmp_in_path = tmp_in.name
        tmp_out_path = tmp_out.name

    try:
        out_path, content_type = compress_video_ffmpeg(tmp_in_path, tmp_out_path)

        with open(out_path, "rb") as f:
            data = f.read()
        minio_internal.put_object(
            MINIO_BUCKET,
            final_path,
            io.BytesIO(data),
            len(data),
            content_type=content_type,
        )
    finally:
        for p in (tmp_in_path, tmp_out_path):
            try:
                if os.path.exists(p):
                    os.remove(p)
            except Exception:
                pass

    try:
        minio_internal.remove_object(MINIO_BUCKET, original_path)
    except Exception as e:
        print(f"[video] warning removing original {original_path}: {e}")

    item.path = final_path
    item.content_type = content_type
    item.status = "ready"
    item.original_path = None
    save_media(item)
    print(f"[video] processed {media_id} -> {final_path}")


def main():
    print("Media worker started. Waiting for jobs...")
    while True:
        job = dequeue_job(block=True, timeout=5)
        if not job:
            continue

        try:
            job_type = job.get("type")
            if job_type == "image":
                process_image_job(job)
            elif job_type == "video":
                process_video_job(job)
            else:
                print(f"[worker] Unknown job type: {job_type}")
        except Exception as e:
            print(f"[worker] Error processing job {job}: {e}")


if __name__ == "__main__":
    main()
