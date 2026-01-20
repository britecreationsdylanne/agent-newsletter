"""
Google Gemini API integration for image generation (Nano Banana)
Using the official google-genai Python SDK
"""

import os
import time
import base64
from typing import Dict, Optional
from google import genai
from google.genai import types


class GeminiClient:
    """Wrapper for Google Gemini API (Nano Banana image generation)"""

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("GOOGLE_AI_API_KEY")
        if not self.api_key:
            raise ValueError("GOOGLE_AI_API_KEY environment variable not set")

        # Initialize the client with API key
        self.client = genai.Client(api_key=self.api_key)
        # Use Gemini 2.5 Flash Image for image generation (Nano Banana)
        self.default_model = os.getenv("DEFAULT_IMAGE_MODEL", "gemini-2.5-flash-image")

    def generate_image(
        self,
        prompt: str,
        model: Optional[str] = None,
        aspect_ratio: str = "16:9",
        image_size: str = "1K",
        number_of_images: int = 1,
    ) -> Dict:
        """
        Generate an image using Nano Banana (Gemini 2.5 Flash Image)

        Args:
            prompt: Image description prompt
            model: Model to use (default: gemini-2.5-flash-image)
            aspect_ratio: Not used for Nano Banana (kept for compatibility)
            image_size: Not used for Nano Banana (kept for compatibility)
            number_of_images: Not used for Nano Banana (kept for compatibility)

        Returns:
            {
                "image_data": "base64_encoded_image",
                "prompt": "original prompt",
                "model": "model-used",
                "cost_estimate": "$0.039",
                "generation_time_ms": 1234
            }
        """
        if not self.api_key:
            raise ValueError("Google AI API key not configured")

        model_name = model or self.default_model
        start_time = time.time()

        try:
            # Use gemini-2.5-flash-image (Nano Banana) for image generation
            print(f"[NANO BANANA] Using model: {model_name}")
            print(f"[NANO BANANA] Prompt: {prompt[:100]}...")

            # Generate image using generate_content
            # Note: gemini-2.5-flash-image is a dedicated image model, no config needed
            response = self.client.models.generate_content(
                model=model_name,
                contents=[prompt]  # MUST be a list!
            )

            generation_time_ms = int((time.time() - start_time) * 1000)

            # Debug: Print response structure
            print(f"[NANO BANANA DEBUG] Response received")
            print(f"[NANO BANANA DEBUG] Response type: {type(response)}")

            # Handle different response formats based on google-genai version
            parts = []
            if hasattr(response, 'parts'):
                parts = response.parts
            elif hasattr(response, 'candidates') and response.candidates:
                # Newer API format
                candidate = response.candidates[0]
                if hasattr(candidate, 'content') and hasattr(candidate.content, 'parts'):
                    parts = candidate.content.parts

            print(f"[NANO BANANA DEBUG] Number of parts: {len(parts)}")

            # Extract image data from response parts using part.as_image()
            image_data = None

            for i, part in enumerate(parts):
                print(f"[NANO BANANA DEBUG] Part {i}: has inline_data = {hasattr(part, 'inline_data')}, has text = {hasattr(part, 'text')}")

                # Use the as_image() method to get Image object (per documentation)
                if hasattr(part, 'inline_data') and part.inline_data:
                    try:
                        # as_image() returns a google.genai.types.Image object
                        image_obj = part.as_image()
                        print(f"[NANO BANANA DEBUG] Got Image object: {type(image_obj)}")

                        # The Image object has a _pil_image attribute for the actual PIL Image
                        if hasattr(image_obj, '_pil_image'):
                            pil_image = image_obj._pil_image
                            print(f"[NANO BANANA DEBUG] Got PIL Image from _pil_image: {type(pil_image)}, size: {pil_image.size}")

                            # Convert PIL Image to base64
                            from io import BytesIO
                            buffer = BytesIO()
                            pil_image.save(buffer, format='PNG')
                            image_bytes = buffer.getvalue()
                            image_data = base64.b64encode(image_bytes).decode('utf-8')

                            print(f"[NANO BANANA DEBUG] Image converted successfully, base64 size: {len(image_data)} bytes")
                            break
                        else:
                            print(f"[NANO BANANA ERROR] Image object has no _pil_image attribute")
                            print(f"[NANO BANANA ERROR] Available attributes: {[a for a in dir(image_obj) if not a.startswith('__')]}")
                    except Exception as img_error:
                        print(f"[NANO BANANA ERROR] Failed to convert image: {img_error}")
                        import traceback
                        traceback.print_exc()

            if not image_data:
                print(f"[NANO BANANA ERROR] No image data found in response")
                print(f"[NANO BANANA ERROR] Response parts count: {len(parts)}")
                if len(parts) > 0:
                    for i, part in enumerate(parts):
                        print(f"[NANO BANANA ERROR] Part {i} has text: {part.text[:200] if hasattr(part, 'text') and part.text else 'None'}")
                raise ValueError("No image data in response")

            # Cost estimate for Nano Banana ($30 per 1M tokens, 1290 tokens per image = ~$0.039)
            cost_per_image = 0.039
            cost_estimate = cost_per_image * number_of_images

            return {
                "image_data": image_data,  # Base64 encoded PNG
                "prompt": prompt,
                "model": model_name,
                "cost_estimate": f"${cost_estimate:.2f}",
                "generation_time_ms": generation_time_ms
            }

        except Exception as e:
            print(f"[NANO BANANA ERROR] Image generation failed: {str(e)}")
            print(f"[NANO BANANA ERROR] Model: {model_name}, Prompt: {prompt[:100]}...")
            import traceback
            traceback.print_exc()
            raise

    def search_web(self, query: str, max_results: int = 5) -> list:
        """
        Search web using Gemini with Google Search grounding

        Args:
            query: Search query
            max_results: Maximum number of results

        Returns:
            List of search results with title, description, url
        """
        try:
            # Use Gemini 2.0 Flash with Google Search grounding
            response = self.client.models.generate_content(
                model="gemini-2.0-flash-exp",
                contents=[f"""Search Google for {max_results} recent, real articles about: {query}

For each article found, provide:
- Title (from the actual article)
- Brief description (1-2 sentences)
- Source URL (the actual URL)
- How recent it is

Return as JSON array:
[
  {{"title": "...", "description": "...", "url": "...", "age": "..."}},
  ...
]

Return ONLY the JSON array."""],
                config=types.GenerateContentConfig(
                    temperature=0.3,
                    max_output_tokens=2000,
                    response_modalities=["TEXT"],
                    tools=[types.Tool(google_search=types.GoogleSearch())]
                )
            )

            # Extract results
            results = []
            if response.text:
                content = response.text.strip()
                # Remove markdown code blocks if present
                if "```json" in content:
                    content = content.split("```json")[1].split("```")[0].strip()
                elif "```" in content:
                    content = content.split("```")[1].split("```")[0].strip()

                try:
                    import json
                    results = json.loads(content)
                    if isinstance(results, list):
                        return results[:max_results]
                except:
                    pass

            return results[:max_results] if results else []

        except Exception as e:
            print(f"Gemini web search error: {e}")
            import traceback
            traceback.print_exc()
            return []

    def search_wedding_news(self, month: str) -> list:
        """Search for wedding venue industry news"""
        query = f"wedding venue industry news statistics data trends 2025 2026 {month}"
        return self.search_web(query, max_results=15)  # Get more results for refresh pool

    def search_wedding_tips(self, month: str) -> list:
        """Search for wedding venue management tips"""
        query = f"wedding venue marketing tips advice strategies 2025 2026 {month}"
        return self.search_web(query, max_results=15)  # Get more results for refresh pool

    def search_wedding_trends(self, month: str, season: str) -> list:
        """Search for seasonal wedding trends"""
        query = f"wedding trends {season} 2025 2026 venue decor planning {month}"
        return self.search_web(query, max_results=15)  # Get more results for refresh pool

    def generate_newsletter_image(
        self,
        section_type: str,
        title: str,
        content_summary: str,
        image_size: str = "1K"
    ) -> Dict:
        """
        Generate an image optimized for newsletter sections

        Args:
            section_type: 'news', 'tip', or 'trend'
            title: Section title
            content_summary: Brief summary of content
            image_size: Image resolution (1K, 2K, 4K)

        Returns:
            Image generation result
        """
        # Base style for all venue newsletter images
        base_style = "Professional, elegant, modern wedding venue photography, warm natural lighting, high-end aesthetic, sophisticated composition"

        # Section-specific styles
        style_additions = {
            "news": "editorial style, newsworthy scene, subtle branding elements, contemporary venue space",
            "tip": "intimate venue details, personalized touches, client-focused perspective, welcoming atmosphere",
            "trend": "seasonal wedding decor, trendy color palette, stylish arrangements, inspirational setting"
        }

        section_style = style_additions.get(section_type, "")

        # Construct optimized prompt
        prompt = f"{title} - {base_style}, {section_style}. {content_summary}"

        return self.generate_image(
            prompt=prompt,
            aspect_ratio="16:9",  # Horizontal for email headers
            image_size=image_size
        )


# Singleton instance
_gemini_client = None


def get_gemini_client() -> GeminiClient:
    """Get or create Gemini client singleton"""
    global _gemini_client
    if _gemini_client is None:
        _gemini_client = GeminiClient()
    return _gemini_client
