
import base64
import binascii
from io import BytesIO
import json
import logging
import os
from typing import Annotated

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
import httpx
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

MCP_URL = "http://127.0.0.1:8000/mcp"
MAX_IMAGE_SIZE_BYTES = 10 * 1024 * 1024
MAX_IMAGE_PIXELS = 40_000_000
REFERENCE_IMAGE_SIZE = (511, 511)
ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}
IMAGE_MODEL = "@cf/black-forest-labs/flux-2-klein-9b"
PRODUCTS = {
    "emerald": "Emerald Green Silk Saree with traditional golden detailing",
}
PRODUCT_COLORS = {"Emerald Green", "Rose Pink", "Royal Purple", "Champagne"}
logger = logging.getLogger(__name__)

app = FastAPI(title="VastrAI API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Local development only
    allow_methods=["*"],
    allow_headers=["*"],
)


class SearchRequest(BaseModel):
    category: str = "saree"
    color: str = ""
    max_price: float = 2500


class CloudflareAIError(Exception):
    def __init__(self, status_code: int, error_details: str = ""):
        self.status_code = status_code
        self.error_details = error_details
        super().__init__(f"Cloudflare Workers AI returned HTTP {status_code}: {error_details}")


def get_cloudflare_credentials() -> tuple[str, str]:
    account_id = os.getenv("CLOUDFLARE_ACCOUNT_ID", "").strip()
    api_token = os.getenv("CLOUDFLARE_API_TOKEN", "").strip()
    if not account_id or not api_token:
        raise HTTPException(
            status_code=503,
            detail=(
                "Cloudflare image generation is not configured. Set "
                "CLOUDFLARE_ACCOUNT_ID and CLOUDFLARE_API_TOKEN on the backend."
            ),
        )
    return account_id, api_token


def cloudflare_error_details(payload: dict) -> str:
    errors = payload.get("errors", [])
    if not isinstance(errors, list):
        return ""

    messages = []
    for error in errors[:3]:
        if isinstance(error, dict):
            code = error.get("code")
            message = error.get("message")
            detail = ": ".join(str(value) for value in (code, message) if value)
            if detail:
                messages.append(detail[:300])

    return "; ".join(messages)


def has_valid_image_signature(content: bytes, mime_type: str) -> bool:
    if mime_type == "image/jpeg":
        return content.startswith(b"\xff\xd8\xff")
    if mime_type == "image/png":
        return content.startswith(b"\x89PNG\r\n\x1a\n")
    if mime_type == "image/webp":
        return len(content) >= 12 and content[:4] == b"RIFF" and content[8:12] == b"WEBP"
    return False


async def read_image(image: UploadFile, field_name: str) -> bytes:
    if image.content_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"{field_name} must be a JPEG, PNG, or WebP image.",
        )

    content = await image.read(MAX_IMAGE_SIZE_BYTES + 1)
    if len(content) > MAX_IMAGE_SIZE_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"{field_name} must be 10 MB or smaller.",
        )
    if not content:
        raise HTTPException(status_code=400, detail=f"{field_name} is empty.")
    if not has_valid_image_signature(content, image.content_type):
        raise HTTPException(
            status_code=400,
            detail=f"{field_name} does not contain a valid {image.content_type} image.",
        )

    return content


def prepare_reference_image(content: bytes) -> bytes:
    try:
        with Image.open(BytesIO(content)) as image:
            image.thumbnail(REFERENCE_IMAGE_SIZE, Image.Resampling.LANCZOS)
            image = image.convert("RGB")
            output = BytesIO()
            image.save(output, format="JPEG", quality=88)
            return output.getvalue()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as error:
        raise HTTPException(status_code=400, detail="The uploaded image could not be decoded.") from error


def generate_try_on(
    photo: bytes,
    photo_type: str,
    product_image: bytes,
    product_image_type: str,
    prompt: str,
) -> tuple[bytes, str] | None:
    account_id, api_token = get_cloudflare_credentials()
    url = (
        "https://api.cloudflare.com/client/v4/accounts/"
        f"{account_id}/ai/run/{IMAGE_MODEL}"
    )
    files = {
        "input_image_0": ("product.jpg", prepare_reference_image(product_image), "image/jpeg"),
        "input_image_1": ("person.jpg", prepare_reference_image(photo), "image/jpeg"),
    }
    editing_prompt = (
        "Image 1 is the person and must remain the same person. Preserve their exact "
        "face, facial features, expression, hairstyle, skin tone, body shape, and pose. "
        "Do not replace, beautify, retouch, or regenerate the face. Image 0 is the "
        "garment reference for design and fabric ONLY; ignore the reference image's "
        "original garment color. Change only the person's clothing to that exact saree "
        "design. Set the garment to the exact color specified in the instruction, "
        "including its fabric and border. Preserve its gold detailing. "
        f"{prompt} Do not change the background, accessories, or any other part of "
        "image 1. Do not add jewellery that is not already present. Make a realistic "
        "photograph, not a collage."
    )
    response = httpx.post(
        url,
        headers={"Authorization": f"Bearer {api_token}"},
        data={
            "prompt": editing_prompt,
            "width": "1024",
            "height": "1024",
        },
        files=files,
        timeout=180,
    )

    try:
        payload = response.json()
    except ValueError:
        raise CloudflareAIError(response.status_code) from None

    if response.is_error or not payload.get("success", False):
        raise CloudflareAIError(
            response.status_code,
            cloudflare_error_details(payload),
        )

    image_data = payload.get("result", {}).get("image")
    if not isinstance(image_data, str) or not image_data:
        return None
    try:
        return base64.b64decode(image_data, validate=True), "image/jpeg"
    except (binascii.Error, ValueError):
        return None


@app.get("/")
async def home():
    return {"message": "VastrAI API is running!"}


@app.post("/try-on")
async def create_try_on(
    photo: Annotated[UploadFile, File()],
    product_image: Annotated[UploadFile, File()],
    product_id: Annotated[str, Form()],
    color: Annotated[str, Form()],
    occasion: Annotated[str, Form(max_length=500)] = "",
):
    get_cloudflare_credentials()
    if product_id not in PRODUCTS:
        raise HTTPException(status_code=400, detail="The selected product is not available.")
    if color not in PRODUCT_COLORS:
        raise HTTPException(status_code=400, detail="The selected product color is not available.")

    photo_bytes = await read_image(photo, "Your photo")
    product_bytes = await read_image(product_image, "The product image")
    description = PRODUCTS[product_id].replace("Emerald Green", color, 1)
    occasion_description = occasion.strip() or "a classic traditional occasion"
    prompt = (
        f"{description}. Use the exact selected {color} color; do not change it to "
        f"another color. The selected color applies to the full saree, including its "
        "main fabric; keep only the reference's gold border and gold embellishments "
        f"gold. Do not copy the reference saree's original base color. Occasion: {occasion_description}."
    )

    try:
        result = await run_in_threadpool(
            generate_try_on,
            photo_bytes,
            photo.content_type,
            product_bytes,
            product_image.content_type,
            prompt,
        )
    except httpx.RequestError:
        logger.exception("Cloudflare Workers AI request failed")
        raise HTTPException(
            status_code=502,
            detail="Could not reach Cloudflare image generation. Please try again.",
        ) from None
    except CloudflareAIError as error:
        logger.error(
            "Cloudflare Workers AI returned HTTP %s: %s",
            error.status_code,
            error.error_details or "No error details returned",
        )
        if error.status_code == 429:
            raise HTTPException(
                status_code=429,
                detail=(
                    "Cloudflare's free daily AI quota may be exhausted. It resets daily; "
                    "stay on the Free plan to avoid paid usage."
                ),
            ) from None
        if error.status_code in {401, 403}:
            raise HTTPException(
                status_code=502,
                detail=(
                    "Cloudflare rejected the API credentials or AI model access. "
                    f"Check that the Account ID and token belong to the same account "
                    f"and the token has Workers AI permissions. Provider message: "
                    f"{error.error_details or 'No details returned.'}"
                ),
            ) from None
        if error.status_code == 404:
            raise HTTPException(
                status_code=502,
                detail=(
                    "Cloudflare could not find the account or image model. Check the "
                    f"Account ID and model access. Provider message: "
                    f"{error.error_details or 'No details returned.'}"
                ),
            ) from None
        raise HTTPException(
            status_code=502,
            detail=(
                f"Cloudflare image generation failed (HTTP {error.status_code}). "
                f"{error.error_details}"
            ).strip(),
        ) from None

    if result is None:
        raise HTTPException(
            status_code=502,
            detail="The image service returned no generated image. Please try again.",
        )

    image_bytes, mime_type = result
    generated_image = f"data:{mime_type};base64,{base64.b64encode(image_bytes).decode('ascii')}"
    return {"generated_image": generated_image, "product_id": product_id, "color": color}


@app.post("/api/search")
async def search_products(request: SearchRequest):
    try:
        async with streamablehttp_client(MCP_URL) as (
            read_stream,
            write_stream,
            _
        ):
            async with ClientSession(
                read_stream, write_stream
            ) as session:
                await session.initialize()

                result = await session.call_tool(
                    "search_products",
                    {
                        "category": request.category,
                        "color": request.color,
                        "max_price": request.max_price,
                    },
                )

                if result.isError:
                    raise HTTPException(
                        status_code=502,
                        detail="MCP product search failed",
                    )

                for item in result.content:
                    if hasattr(item, "text"):
                        try:
                            return json.loads(item.text)
                        except json.JSONDecodeError:
                            return {"result": item.text}

                return {"result": "No product data returned"}

    except HTTPException:
        raise
    except Exception as error:
        raise HTTPException(
            status_code=502,
            detail=f"Backend connection failed: {error}",
        )
