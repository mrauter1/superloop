from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from tempfile import SpooledTemporaryFile
import hashlib
import io
import uuid

from fastapi import Request, UploadFile
from PIL import Image

from shared.config import Settings

ALLOWED_IMAGE_MIME_TYPES = {"image/png", "image/jpeg"}
MULTIPART_PART_SIZE_SLACK_BYTES = 64 * 1024


class UploadValidationError(ValueError):
    """Raised when an uploaded image violates Stage 1 rules."""


@dataclass(frozen=True)
class ValidatedImage:
    original_filename: str
    mime_type: str
    sha256: str
    size_bytes: int
    width: int
    height: int
    data: bytes


async def parse_multipart_form(request: Request, settings: Settings):
    return await request.form(
        max_files=settings.max_images_per_message,
        max_part_size=settings.max_image_bytes + MULTIPART_PART_SIZE_SLACK_BYTES,
    )


def get_form_images(form, field_name: str = "attachments") -> list[UploadFile]:
    values = form.getlist(field_name)
    return [
        value
        for value in values
        if isinstance(value, UploadFile) and (value.filename or "").strip()
    ]


async def validate_image_upload(upload: UploadFile, settings: Settings) -> ValidatedImage:
    if upload.content_type not in ALLOWED_IMAGE_MIME_TYPES:
        raise UploadValidationError(f"Unsupported image type: {upload.content_type}")

    data = await upload.read()
    if len(data) > settings.max_image_bytes:
        raise UploadValidationError("Image exceeds MAX_IMAGE_BYTES")

    try:
        image = Image.open(io.BytesIO(data))
        image.verify()
        reopened = Image.open(io.BytesIO(data))
        width, height = reopened.size
    except Exception as exc:  # pragma: no cover - Pillow raises multiple types here
        raise UploadValidationError("Uploaded file is not a valid image") from exc

    return ValidatedImage(
        original_filename=upload.filename or "upload",
        mime_type=upload.content_type,
        sha256=hashlib.sha256(data).hexdigest(),
        size_bytes=len(data),
        width=width,
        height=height,
        data=data,
    )


def build_attachment_storage_path(settings: Settings, *, ticket_id: uuid.UUID, attachment_id: uuid.UUID, extension: str) -> Path:
    return settings.uploads_dir / str(ticket_id) / f"{attachment_id}{extension}"


def persist_validated_image(path: Path, image: ValidatedImage) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(image.data)
