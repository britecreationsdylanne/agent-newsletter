"""
OpenAI API integration for content generation
"""

import os
import time
from typing import Dict, List, Optional
from openai import OpenAI
import json


class OpenAIClient:
    """Wrapper for OpenAI API calls"""

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self.client = OpenAI(api_key=self.api_key) if self.api_key else None
        self.default_model = os.getenv("DEFAULT_CONTENT_MODEL", "gpt-4o")

    def generate_content(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 2000,
        tools: Optional[List] = None,
    ) -> Dict:
        """
        Generate content using OpenAI

        Args:
            prompt: User prompt
            system_prompt: System instructions
            model: Model to use (default: gpt-4o)
            temperature: Creativity (0-2)
            max_tokens: Maximum response length
            tools: Optional function calling tools

        Returns:
            {
                "content": "generated text",
                "model": "model-used",
                "tokens": 123,
                "cost_estimate": "$0.05"
            }
        """
        if not self.client:
            raise ValueError("OpenAI API key not configured")

        model = model or self.default_model
        start_time = time.time()

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        # Build kwargs
        kwargs = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
        }

        # GPT-5.x and newer models use max_completion_tokens instead of max_tokens
        if model and (model.startswith("gpt-5") or model.startswith("o1") or model.startswith("o3")):
            kwargs["max_completion_tokens"] = max_tokens
        else:
            kwargs["max_tokens"] = max_tokens

        # Add tools if provided (for web search)
        if tools:
            kwargs["tools"] = tools

        response = self.client.chat.completions.create(**kwargs)

        latency_ms = int((time.time() - start_time) * 1000)
        tokens_used = response.usage.total_tokens

        # Rough cost estimation (update with actual pricing)
        cost_per_1k_tokens = 0.03 if "gpt-4" in model else 0.002
        cost_estimate = (tokens_used / 1000) * cost_per_1k_tokens

        return {
            "content": response.choices[0].message.content,
            "model": model,
            "tokens": tokens_used,
            "cost_estimate": f"${cost_estimate:.4f}",
            "latency_ms": latency_ms,
            "finish_reason": response.choices[0].finish_reason,
            "raw_response": response,  # Include full response for tool calls
        }

    def generate_newsletter_section(
        self,
        section_type: str,
        topic: Dict,
        brand_voice: Dict,
        structure: Dict,
    ) -> Dict:
        """
        Generate a complete newsletter section

        Args:
            section_type: 'news', 'tip', or 'trend'
            topic: Selected topic dict with title, description, keywords
            brand_voice: Brand voice guidelines
            structure: Section structure requirements

        Returns:
            Complete section content
        """
        system_prompt = f"""You are a professional content writer for wedding venue marketing.

BRAND VOICE:
- Tone: {brand_voice.get('tone')}
- Style: {brand_voice.get('style')}
- Perspective: {brand_voice.get('perspective')}

AVOID:
{chr(10).join('- ' + item for item in brand_voice.get('avoid', []))}

SECTION STRUCTURE ({section_type}):
{chr(10).join('- ' + item for item in structure.get('structure', []))}

Write in a {structure.get('tone')} tone.

IMPORTANT STYLE RULES:
- Use % symbol, not "percent"
- Use serial commas in lists
- Use em dashes with spaces (—) not hyphens (-)
- Use gender-neutral language (partner, not bride/groom)
- Hyphenate "lab-grown"
- Title case for headlines, sentence case for body"""

        user_prompt = f"""Write a {section_type} section about: {topic['title']}

Description: {topic.get('description', '')}
Keywords: {', '.join(topic.get('keywords', []))}

Source for reference: {topic.get('source_url', 'N/A')}

Generate the complete section following the structure guidelines."""

        result = self.generate_content(
            prompt=user_prompt,
            system_prompt=system_prompt,
            temperature=0.7,
            max_tokens=1500,
        )

        # Parse the AI response into structured fields
        # This is simplified - you'd want more robust parsing
        content_text = result['content']

        return {
            **result,
            "raw_content": content_text,
            "section_type": section_type,
        }

    def search_web_responses_api(self, query: str, max_results: int = 15, exclude_urls: list = None) -> list:
        """
        Search web using OpenAI Responses API with web_search tool

        Uses the Responses API endpoint which has native web_search tool support.

        Args:
            query: Search query with context
            max_results: Maximum number of results (default 15)
            exclude_urls: List of URLs to exclude (for refresh functionality)

        Returns:
            List of search results with title, description (summary), url, publisher, published_date
        """
        try:
            print(f"\n{'='*60}")
            print(f"[OpenAI Responses API] STARTING SEARCH")
            print(f"[OpenAI Responses API] Query preview: {query[:150]}...")
            print(f"[OpenAI Responses API] Requesting {max_results} articles...")

            # Add exclusion list to prompt if provided
            exclude_urls = exclude_urls or []
            if exclude_urls:
                exclude_text = "\n".join(f"- {u}" for u in exclude_urls[:400])  # Cap for token sanity
                full_prompt = f"""{query}

Exclusions:
Do NOT include any of these URLs (previously used):
{exclude_text}

Return at least 25 candidate results if possible (we will dedupe/trim to {max_results} in code).
No extra keys. No commentary outside JSON."""
            else:
                full_prompt = f"""{query}

Return at least 25 candidate results if possible (we will dedupe/trim to {max_results} in code).
No extra keys. No commentary outside JSON."""

            # Use Responses API with web_search tool
            response = self.client.responses.create(
                model="gpt-4o",
                tools=[{"type": "web_search"}],
                max_tool_calls=1,
                include=["web_search_call.action.sources"],  # Expose sources
                input=full_prompt,
            )

            # Diagnostics: Check if web_search actually happened
            print(f"[OpenAI Responses API] Response received from API")
            outputs = getattr(response, "output", []) or []
            print(f"[OpenAI Responses API] Response has {len(outputs)} output items")
            web_calls = [o for o in outputs if getattr(o, "type", None) == "web_search_call"]

            if not web_calls:
                print("[OpenAI Responses API] ERROR: No web_search_call found in response.output")
                print(f"[OpenAI Responses API] Output types present: {[getattr(o, 'type', 'unknown') for o in outputs]}")
                output_text = getattr(response, "output_text", "")
                if output_text:
                    print(f"[OpenAI Responses API] output_text preview: {output_text[:500]}")
                return []

            print(f"[OpenAI Responses API] Found {len(web_calls)} web_search_call(s)")

            # Debug output types
            print(f"[OpenAI Responses API DEBUG] Output item types: {[getattr(o, 'type', None) for o in outputs]}")

            # Extract web sources from web_search_call.action.sources
            web_sources = []
            for o in outputs:
                if getattr(o, "type", None) == "web_search_call":
                    action = getattr(o, "action", None)
                    sources = getattr(action, "sources", None)
                    if isinstance(sources, list) and sources:
                        for s in sources:
                            if isinstance(s, dict):
                                web_sources.append(s)
                            else:
                                web_sources.append({
                                    "url": getattr(s, "url", None),
                                    "title": getattr(s, "title", None),
                                })
                        # Keep only entries with real URLs
                        web_sources = [x for x in web_sources if isinstance(x.get("url"), str) and x["url"].startswith("http")]
                    break

            print(f"[OpenAI Responses API DEBUG] Extracted {len(web_sources)} web sources from web_search_call")
            sources_with_titles = sum(1 for s in web_sources if s.get('title'))
            print(f"[OpenAI Responses API DEBUG] Sources have titles: {sources_with_titles}/{len(web_sources)}")

            # If sources don't have titles, we need to match by URL or use sources directly
            use_sources_directly = sources_with_titles == 0

            # Extract JSON results from output_text
            output_text = response.output_text
            if not output_text:
                print("[OpenAI Responses API] No output_text in response")
                return []

            # Parse JSON, handling markdown fences if present
            import re
            text = output_text.strip()
            if text.startswith("```"):
                text = re.sub(r"^```[a-zA-Z]*\n", "", text)
                text = re.sub(r"\n```$", "", text).strip()

            try:
                data = json.loads(text)
            except json.JSONDecodeError as e:
                print(f"[OpenAI Responses API ERROR] JSON parsing failed: {e}")
                print(f"[OpenAI Responses API ERROR] Text preview: {text[:200]}...")
                return []

            # Handle both formats: {"results": [...]} or just [...]
            if isinstance(data, list):
                # OpenAI returned array directly
                raw_results = data
                print(f"[OpenAI Responses API] Received results as direct array")
            elif isinstance(data, dict):
                raw_results = data.get("results", [])
                print(f"[OpenAI Responses API] Received results in dict format")
            else:
                print(f"[OpenAI Responses API ERROR] Unexpected JSON type: {type(data)}")
                return []

            if not isinstance(raw_results, list):
                print("[OpenAI Responses API] Results is not a list")
                return []

            print(f"[OpenAI Responses API DEBUG] Model returned {len(raw_results)} results in JSON")
            # Skip debug printing of titles/URLs to avoid Unicode errors

            # Clean and deduplicate results
            from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode
            import re

            # Fuzzy title matching helpers
            STOPWORDS = {
                "the","a","an","and","or","but","to","of","in","on","for","with","at","by",
                "from","as","is","are","was","were","be","been","being","it","its","this",
                "that","these","those","you","your","we","our","they","their"
            }

            def normalize_text(s: str) -> str:
                s = (s or "").lower()
                s = re.sub(r"\s+", " ", s)
                s = re.sub(r"[^a-z0-9\s]", "", s)
                return s.strip()

            def tokens(s: str) -> set:
                s = normalize_text(s)
                ts = [t for t in s.split(" ") if t and t not in STOPWORDS and len(t) > 2]
                return set(ts)

            def jaccard(a: set, b: set) -> float:
                if not a or not b:
                    return 0.0
                inter = len(a & b)
                union = len(a | b)
                return inter / union if union else 0.0

            def best_source_for_title(model_title: str, sources: list) -> tuple:
                mt = tokens(model_title)
                best = None
                best_score = 0.0

                for s in sources:
                    stitle = str(s.get("title",""))
                    score = jaccard(mt, tokens(stitle))
                    if score > best_score:
                        best_score = score
                        best = s

                return best, best_score

            def normalize_url(url: str) -> str:
                if not url:
                    return url
                try:
                    p = urlparse(url.strip())
                    scheme = (p.scheme or "https").lower()
                    netloc = p.netloc.lower()
                    path = p.path or "/"
                    tracking_keys = {
                        "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
                        "gclid", "fbclid", "mc_cid", "mc_eid", "mkt_tok"
                    }
                    q = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True)
                         if k.lower() not in tracking_keys]
                    query = urlencode(q, doseq=True)
                    return urlunparse((scheme, netloc, path, p.params, query, ""))
                except:
                    return url.strip()

            exclude_norm = {normalize_url(u) for u in exclude_urls}
            cleaned = []
            seen_norm = set()

            # Track which sources we've used
            used_source_indices = set()

            for idx, item in enumerate(raw_results):
                if not isinstance(item, dict):
                    continue

                title = str(item.get("title", "")).strip()
                url_raw = str(item.get("url", "")).strip()
                publisher = str(item.get("publisher", "")).strip()
                published_date = str(item.get("published_date", "")).strip() if item.get("published_date") else None
                summary = str(item.get("summary", "")).strip()

                # If model gave a real URL, use it. Otherwise recover from web_sources
                if url_raw.startswith("http://") or url_raw.startswith("https://"):
                    url = url_raw
                else:
                    # Attempt to recover URL from web_search sources
                    url = ""
                    if not use_sources_directly and title:
                        # Try fuzzy matching by title
                        for sidx, s in enumerate(web_sources):
                            if sidx in used_source_indices:
                                continue
                            best_source, best_score = best_source_for_title(title, [s])
                            # Require at least 30% similarity (lowered from 40% to improve result coverage)
                            if best_score >= 0.3:
                                url = str(s.get("url", "")).strip()
                                # Also update publisher from source if not provided
                                if not publisher and s.get("publisher"):
                                    publisher = str(s.get("publisher", "")).strip()
                                used_source_indices.add(sidx)
                                break

                    # NOTE: Removed index-based fallback that caused off-by-one URL/summary mismatch
                    # If fuzzy matching didn't find a URL, skip this result rather than mismatching
                    if not url:
                        print(f"[OpenAI Responses API] Skipping result with no URL match: {title[:50]}...")
                        continue

                if not url or not title:
                    continue

                nurl = normalize_url(url)
                if nurl in exclude_norm or nurl in seen_norm:
                    continue

                # Quality check
                if len(summary) < 20:
                    continue

                if not publisher:
                    try:
                        publisher = urlparse(nurl).netloc
                    except:
                        publisher = ""

                cleaned.append({
                    "title": title,
                    "description": summary,
                    "url": nurl,
                    "publisher": publisher,
                    "published_date": published_date,
                    "age": self._format_published_date(published_date) if published_date else ""
                })
                seen_norm.add(nurl)

                if len(cleaned) >= max_results:
                    break

            print(f"[OpenAI Responses API] FINAL: Returned {len(cleaned)} articles after dedup")
            print(f"{'='*60}\n")
            return cleaned

        except Exception as e:
            print(f"[OpenAI Responses API] EXCEPTION: {e}")
            import traceback
            traceback.print_exc()
            return []

    def _format_published_date(self, date_str: str) -> str:
        """Convert published_date (YYYY-MM-DD) to relative format like '2 days ago'"""
        if not date_str:
            return ""
        try:
            from datetime import datetime
            pub_date = datetime.strptime(date_str, "%Y-%m-%d")
            now = datetime.now()
            delta = now - pub_date

            if delta.days == 0:
                return "today"
            elif delta.days == 1:
                return "1 day ago"
            elif delta.days < 7:
                return f"{delta.days} days ago"
            elif delta.days < 30:
                weeks = delta.days // 7
                return f"{weeks} week{'s' if weeks > 1 else ''} ago"
            else:
                months = delta.days // 30
                return f"{months} month{'s' if months > 1 else ''} ago"
        except:
            return ""

    def search_wedding_news(self, month: str, exclude_urls: list = None) -> list:
        """Search for wedding venue industry news - returns 15 results"""
        query = """
You are curating the "Latest Wedding Industry News" section of a newsletter for wedding venue owners/operators.

IMPORTANT: Use the web_search tool to find sources on the open web.

Task:
Search the web for latest wedding industry news relevant to wedding venues.

Venue relevance focus:
- venue operations, logistics, staffing
- bookings/demand, pricing, profitability
- catering/bar expectations, rentals, vendor coordination
- insurance/liability, contracts/policies, permits/regulations
- marketing/SEO, lead conversion, tours, client experience
- technology/tools used by venues

Recency:
Prioritize items published in the last 14 days when possible.

Output requirements (JSON ONLY):
Return an object with key "results" which is an array of items.
Each item must include:
- title (string)
- url (string)
- publisher (string)
- published_date (string in YYYY-MM-DD OR null if not available)
- summary (1-2 sentences, written for a venue operator, include why it matters / action angle)

Section-specific guidance:
Look for real news (announcements, reports, market updates, platform changes, regulatory changes)
that would affect a wedding venue business.
"""
        return self.search_web_responses_api(query, max_results=15, exclude_urls=exclude_urls)

    def search_wedding_tips(self, month: str, exclude_urls: list = None) -> list:
        """Search for wedding venue management tips - returns 15 results"""
        query = """
You are curating the "Wedding Venue Tips" section of a newsletter for wedding venue owners/operators.

IMPORTANT: Use the web_search tool to find sources on the open web.

Task:
Search the web for practical, actionable tips relevant to wedding venue operations.

Topic focus:
- sales techniques, lead handling, conversion strategies
- pricing models, packages, add-ons, upsells
- bar/catering operations, menu planning, beverage trends
- staffing, training, team management
- timeline logistics, day-of coordination
- risk management, contract clauses, insurance
- guest flow, accessibility, parking, noise management
- vendor coordination, preferred vendor lists
- marketing/SEO, social media content, reviews
- technology/tools for venue management

Recency:
Prioritize content published in the last 90 days when possible.

Output requirements (JSON ONLY):
Return an object with key "results" which is an array of items.
Each item must include:
- title (string)
- url (string)
- publisher (string)
- published_date (string in YYYY-MM-DD OR null if not available)
- summary (1-2 sentences, written for a venue operator, include clear "how to use this" takeaway)

Section-specific guidance:
Look for actionable advice, best practices, how-to guides, and strategic tips
that venue operators can implement to improve their business.
"""
        return self.search_web_responses_api(query, max_results=15, exclude_urls=exclude_urls)

    def search_wedding_trends(self, month: str, season: str, exclude_urls: list = None) -> list:
        """Search for seasonal wedding trends - returns 15 results"""
        query = f"""
You are curating the "Wedding Trends" section of a newsletter for wedding venue owners/operators.

Task:
Search the web for {season} 2025/2026 wedding trends that venue operators should know about.

Trend focus:
- decor trends, ceremony/reception styles
- color palettes, floral arrangements
- entertainment preferences, music trends
- food/beverage trends, catering styles
- venue aesthetics, setup requirements
- photography/videography styles
- design elements that impact venue setup/configuration
- lighting, furniture, rental needs
- guest experience expectations

Recency:
Prioritize content published in the last 90 days when possible.

Output requirements (JSON ONLY):
Return an object with key "results" which is an array of items.
Each item must include:
- title (string)
- url (string)
- publisher (string)
- published_date (string in YYYY-MM-DD OR null if not available)
- summary (1-2 sentences, written for a venue operator, explain why this trend matters and what they should prepare for)

Section-specific guidance:
Look for trend forecasts, style guides, design inspiration, and industry predictions
that help venues understand what couples will be requesting for {season} weddings.
"""
        return self.search_web_responses_api(query, max_results=15, exclude_urls=exclude_urls)


# Singleton instance
_openai_client = None


def get_openai_client() -> OpenAIClient:
    """Get or create OpenAI client singleton"""
    global _openai_client
    if _openai_client is None:
        _openai_client = OpenAIClient()
    return _openai_client
