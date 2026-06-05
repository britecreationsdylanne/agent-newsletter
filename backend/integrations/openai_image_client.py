"""
OpenAI image generation integration (GPT Image 2)
Drop-in replacement for the Gemini image path. Returns base64 PNG image data
in the same shape the app's /api/generate-images endpoints expect.
"""

import os
import time
from typing import Dict, Optional
from openai import OpenAI


# Map app-level aspect ratios to GPT Image 2 supported sizes.
# The newsletter pipeline resizes to exact dimensions afterward, so we just
# pick the closest supported aspect.
_ASPECT_TO_SIZE = {
    "16:9": "1536x1024",   # landscape (closest supported is 3:2)
    "3:2": "1536x1024",
    "1:1": "1024x1024",
    "9:16": "1024x1536",   # portrait
    "2:3": "1024x1536",
}

# Rough per-image cost by quality at standard size (USD).
_QUALITY_COST = {
    "low": 0.01,
    "medium": 0.06,
    "high": 0.22,
    "auto": 0.06,
}


class OpenAIImageClient:
    """Wrapper for OpenAI image generation (GPT Image 2)."""

    def __init__(self, api_key: Optional[str] = None):
        # Support Secret Manager underscore-prefixed fallback, like the other clients.
        self.api_key = api_key or os.getenv("OPENAI_API_KEY") or os.getenv("_OPENAI_API_KEY")
        self.client = OpenAI(api_key=self.api_key) if self.api_key else None
        self.default_model = os.getenv("DEFAULT_IMAGE_MODEL", "gpt-image-2")
        self.default_quality = os.getenv("DEFAULT_IMAGE_QUALITY", "medium")

        if self.client:
            print("[OK] OpenAI image client initialized (GPT Image 2)")
        else:
            print("[WARNING] OPENAI_API_KEY not set - image generation disabled")

    def is_available(self) -> bool:
        """Check if the OpenAI image client is configured."""
        return self.client is not None

    def generate_image(
        self,
        prompt: str,
        model: Optional[str] = None,
        aspect_ratio: str = "16:9",
        image_size: str = "1K",
        number_of_images: int = 1,
        quality: Optional[str] = None,
    ) -> Dict:
        """
        Generate an image using GPT Image 2.

        Args:
            prompt: Image description prompt
            model: Model to use (default: gpt-image-2)
            aspect_ratio: '16:9', '1:1', '9:16', etc. (mapped to a supported size)
            image_size: Unused (kept for interface parity with the Gemini client)
            number_of_images: Number of images to generate (n)
            quality: 'low' | 'medium' | 'high' | 'auto' (default from env)

        Returns:
            {
                "image_data": "<base64 PNG>",
                "image_base64": "<base64 PNG>",   # alias for compatibility
                "prompt": "...",
                "model": "gpt-image-2",
                "cost_estimate": "$0.06",
                "generation_time_ms": 1234
            }
        """
        if not self.is_available():
            print("[GPT Image 2] API not available - skipping image generation")
            return None

        model_name = model or self.default_model
        quality = quality or self.default_quality
        size = _ASPECT_TO_SIZE.get(aspect_ratio, "1536x1024")
        start_time = time.time()

        try:
            print(f"[GPT IMAGE 2] Using model: {model_name} | size: {size} | quality: {quality}")
            print(f"[GPT IMAGE 2] Prompt: {prompt[:100]}...")

            response = self.client.images.generate(
                model=model_name,
                prompt=prompt,
                size=size,
                quality=quality,
                n=number_of_images,
            )

            generation_time_ms = int((time.time() - start_time) * 1000)

            # GPT Image models return base64 by default in data[].b64_json
            image_data = None
            if response and getattr(response, "data", None):
                image_data = getattr(response.data[0], "b64_json", None)

            if not image_data:
                print("[GPT IMAGE 2 ERROR] No image data found in response")
                raise ValueError("No image data in response")

            cost_estimate = _QUALITY_COST.get(quality, 0.06) * number_of_images

            return {
                "image_data": image_data,        # Base64 encoded PNG
                "image_base64": image_data,      # Alias for callers that read image_base64
                "prompt": prompt,
                "model": model_name,
                "cost_estimate": f"${cost_estimate:.2f}",
                "generation_time_ms": generation_time_ms,
            }

        except Exception as e:
            print(f"[GPT IMAGE 2 ERROR] Image generation failed: {str(e)}")
            print(f"[GPT IMAGE 2 ERROR] Model: {model_name}, Prompt: {prompt[:100]}...")
            import traceback
            traceback.print_exc()
            raise

    def generate_newsletter_image(
        self,
        section_type: str,
        title: str,
        content_summary: str,
        image_size: str = "1K",
    ) -> Dict:
        """Generate an image optimized for newsletter sections (parity helper)."""
        base_style = (
            "Professional, elegant, modern photography, warm natural lighting, "
            "high-end aesthetic, sophisticated composition"
        )
        style_additions = {
            "news": "editorial style, newsworthy scene, contemporary setting",
            "tip": "intimate details, client-focused perspective, welcoming atmosphere",
            "trend": "seasonal palette, stylish arrangements, inspirational setting",
        }
        section_style = style_additions.get(section_type, "")
        prompt = f"{title} - {base_style}, {section_style}. {content_summary}"
        return self.generate_image(prompt=prompt, aspect_ratio="16:9", image_size=image_size)


# Singleton instance
_openai_image_client = None


def get_openai_image_client() -> OpenAIImageClient:
    """Get or create the OpenAI image client singleton."""
    global _openai_image_client
    if _openai_image_client is None:
        _openai_image_client = OpenAIImageClient()
    return _openai_image_client
