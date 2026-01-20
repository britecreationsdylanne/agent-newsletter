"""
Perplexity API Client

Uses Perplexity's sonar model for research queries with citations.
Excellent for finding recent news with proper source attribution.
"""

import os
import json
import requests
from typing import List, Dict
from datetime import datetime


class PerplexityClient:
    """Client for Perplexity API"""

    def __init__(self, api_key: str = None):
        """Initialize Perplexity client"""
        self.api_key = api_key or os.getenv('PERPLEXITY_API_KEY')
        self.base_url = "https://api.perplexity.ai"

        if self.api_key:
            print("[OK] Perplexity initialized")
        else:
            print("[WARNING] PERPLEXITY_API_KEY not found - Perplexity search disabled")

    def is_available(self) -> bool:
        """Check if Perplexity API is configured"""
        return bool(self.api_key)

    def search(
        self,
        query: str,
        time_window: str = "30d",
        geography: str = "",
        max_results: int = 4
    ) -> List[Dict]:
        """
        Search using Perplexity API with sonar model

        Args:
            query: Search query
            time_window: Time filter (7d, 30d, 90d)
            geography: Optional geographic focus
            max_results: Number of results to return

        Returns:
            List of results with shared schema
        """
        if not self.is_available():
            print("[Perplexity] API key not configured")
            return []

        try:
            # Build the search prompt
            time_context = {
                '7d': 'from the past week',
                '30d': 'from the past month',
                '90d': 'from the past 3 months'
            }.get(time_window, 'recent')

            geo_context = f" Focus on {geography}." if geography else ""

            system_prompt = f"""You are a research assistant helping wedding venue owners find relevant industry news and insights.

Search for {time_context} articles and news.{geo_context}

For each finding, provide:
1. A clear title summarizing the key point
2. The source URL (must be a real, working URL)
3. The publisher/source name
4. A 2-3 sentence summary explaining the finding
5. Why this matters for wedding venue operators

Return your findings as a JSON array with this structure:
{{
    "results": [
        {{
            "title": "Article title or key finding",
            "url": "https://actual-source-url.com/article",
            "publisher": "Source name",
            "published_date": "YYYY-MM-DD or null if unknown",
            "summary": "2-3 sentence summary of the article",
            "venue_implications": "Why this matters for wedding venues"
        }}
    ]
}}

Important:
- Only include results with REAL, verifiable URLs
- Focus on actionable insights for wedding venue businesses
- Include specific data points and statistics when available
- Return exactly {max_results} results"""

            # Make API request
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }

            payload = {
                "model": "sonar",  # sonar has web search built-in
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": query}
                ],
                "temperature": 0.2,
                "max_tokens": 2000
            }

            print(f"[Perplexity] Searching: {query[:100]}...")

            response = requests.post(
                f"{self.base_url}/chat/completions",
                headers=headers,
                json=payload,
                timeout=30
            )

            if response.status_code != 200:
                print(f"[Perplexity] API error: {response.status_code} - {response.text[:200]}")
                return []

            data = response.json()

            # Debug: log raw response structure
            print(f"[Perplexity] Response keys: {data.keys()}")

            # Extract content from response
            choice = data.get('choices', [{}])[0]
            content = choice.get('message', {}).get('content', '')

            # Perplexity returns citations in a separate field
            citations = data.get('citations', [])

            print(f"[Perplexity] Content length: {len(content)}, Citations: {len(citations)}")

            if not content:
                print("[Perplexity] No content in response")
                return []

            # If we have citations, use them to build results
            if citations:
                results = self._parse_with_citations(content, citations, max_results)
            else:
                # Try to parse JSON from response (legacy approach)
                results = self._parse_results(content, max_results)

            # Add source_card field
            for r in results:
                r['source_card'] = 'perplexity'
                r['category'] = 'research'

            print(f"[Perplexity] Found {len(results)} results")
            return results

        except requests.exceptions.Timeout:
            print("[Perplexity] Request timed out")
            return []
        except requests.exceptions.RequestException as e:
            print(f"[Perplexity] Request error: {e}")
            return []
        except Exception as e:
            print(f"[Perplexity] Error: {e}")
            import traceback
            traceback.print_exc()
            return []

    def _parse_with_citations(self, content: str, citations: list, max_results: int) -> List[Dict]:
        """Parse results using Perplexity's citations array with better title extraction"""
        import re

        results = []

        # Split content into sentences for analysis
        sentences = re.split(r'(?<=[.!?])\s+', content)

        # Citations is a list of URLs that Perplexity used as sources
        for i, url in enumerate(citations[:max_results]):
            if not url or not isinstance(url, str):
                continue

            # Extract domain for publisher name
            domain = self._extract_domain(url)
            citation_marker = f"[{i+1}]"

            # Find ALL sentences containing this citation marker
            related_sentences = []
            for sentence in sentences:
                if citation_marker in sentence:
                    # Clean up the sentence - remove citation markers
                    clean = re.sub(r'\[\d+\]', '', sentence).strip()
                    if clean and len(clean) > 20:
                        related_sentences.append(clean)

            # Also check for domain mentions if no citation marker found
            if not related_sentences:
                for sentence in sentences:
                    if domain.lower() in sentence.lower():
                        clean = re.sub(r'\[\d+\]', '', sentence).strip()
                        if clean and len(clean) > 20:
                            related_sentences.append(clean)
                            break

            # Extract a good title from the content
            title = self._extract_title_from_sentences(related_sentences, domain)

            # Build snippet from remaining sentences
            snippet = ' '.join(related_sentences[:2])[:300] if related_sentences else f"Source from {domain}"

            # Generate venue implications from the content
            venue_implications = self._generate_venue_angle(related_sentences)

            results.append({
                'title': title,
                'url': url,
                'publisher': domain,
                'published_at': '',
                'snippet': snippet,
                'venue_implications': venue_implications,
                'source_card': 'perplexity',
                'category': 'research'
            })

        return results

    def _extract_title_from_sentences(self, sentences: list, domain: str) -> str:
        """Extract a compelling title from sentence content"""
        if not sentences:
            return f"Industry Update from {domain}"

        # Take the first sentence as the basis
        first = sentences[0]

        # If it's too long, try to extract the key phrase
        if len(first) > 80:
            # Look for key patterns that make good titles
            import re

            # Pattern: "X is/are Y" - extract the core claim
            match = re.search(r'^([^,]{20,70})', first)
            if match:
                title = match.group(1).strip()
                # Clean up trailing words that don't make sense alone
                title = re.sub(r'\s+(and|or|with|the|a|an|to|for|in|on|by)$', '', title, flags=re.I)
                if len(title) > 25:
                    return title

            # Just truncate intelligently at a word boundary
            words = first.split()
            title = ''
            for word in words:
                if len(title + ' ' + word) > 70:
                    break
                title = (title + ' ' + word).strip()
            return title if title else first[:70]

        return first

    def _generate_venue_angle(self, sentences: list) -> str:
        """Generate venue-focused implications from content"""
        if not sentences:
            return "Review this source for wedding venue insights"

        content = ' '.join(sentences).lower()

        # Check for specific topics and provide targeted implications
        if any(word in content for word in ['cost', 'price', 'expense', 'budget', 'spending']):
            return "Consider how these cost trends affect your pricing strategy and client expectations"
        elif any(word in content for word in ['trend', 'popular', 'growing', 'rising']):
            return "Evaluate whether to incorporate this trend into your venue offerings"
        elif any(word in content for word in ['booking', 'demand', 'reservation', 'capacity']):
            return "Use this insight to optimize your booking strategy and availability"
        elif any(word in content for word in ['technology', 'digital', 'software', 'app']):
            return "Assess if this technology could improve your venue operations"
        elif any(word in content for word in ['staff', 'hiring', 'labor', 'employee']):
            return "Factor this into your staffing plans and operational costs"
        elif any(word in content for word in ['sustainable', 'eco', 'green', 'environment']):
            return "Consider sustainability initiatives that align with these market expectations"
        else:
            return "Share this industry insight with couples to demonstrate your expertise"

    def _parse_results(self, content: str, max_results: int) -> List[Dict]:
        """Parse JSON results from Perplexity response (legacy approach)"""
        import re

        # Try to extract JSON from the response
        # Handle markdown code blocks
        text = content.strip()
        if text.startswith("```"):
            text = re.sub(r"^```[a-zA-Z]*\n", "", text)
            text = re.sub(r"\n```$", "", text).strip()

        # Try to find JSON object in text
        json_match = re.search(r'\{[\s\S]*"results"[\s\S]*\}', text)
        if json_match:
            text = json_match.group(0)

        try:
            data = json.loads(text)
            results = data.get('results', [])

            # Normalize and validate results
            cleaned = []
            for r in results[:max_results]:
                if not isinstance(r, dict):
                    continue

                url = r.get('url', '')
                title = r.get('title', '')

                # Skip results without URL or title
                if not url or not title:
                    continue

                # Skip placeholder URLs
                if 'example.com' in url or 'placeholder' in url.lower():
                    continue

                cleaned.append({
                    'title': title,
                    'url': url,
                    'publisher': r.get('publisher', self._extract_domain(url)),
                    'published_at': r.get('published_date', ''),
                    'snippet': r.get('summary', ''),
                    'venue_implications': r.get('venue_implications', ''),
                    'source_card': 'perplexity',
                    'category': 'research'
                })

            return cleaned

        except json.JSONDecodeError as e:
            print(f"[Perplexity] JSON parse error: {e}")
            # Try to extract useful info from plain text response
            return self._parse_plain_text(content, max_results)

    def _parse_plain_text(self, content: str, max_results: int) -> List[Dict]:
        """Fallback: extract URLs and context from plain text response"""
        import re

        results = []
        # Find URLs in the text
        url_pattern = r'https?://[^\s<>"{}|\\^`\[\]]+'
        urls = re.findall(url_pattern, content)

        for url in urls[:max_results]:
            # Try to extract context around the URL
            domain = self._extract_domain(url)
            results.append({
                'title': f'Finding from {domain}',
                'url': url,
                'publisher': domain,
                'published_at': '',
                'snippet': 'See source for details',
                'venue_implications': 'Review this source for wedding venue insights',
                'source_card': 'perplexity',
                'category': 'research'
            })

        return results

    def _extract_domain(self, url: str) -> str:
        """Extract domain name from URL"""
        try:
            from urllib.parse import urlparse
            parsed = urlparse(url)
            domain = parsed.netloc
            # Remove www. prefix
            if domain.startswith('www.'):
                domain = domain[4:]
            return domain
        except:
            return 'Unknown'

    def search_wedding_research(
        self,
        topic: str,
        geography: str = "",
        time_window: str = "30d"
    ) -> List[Dict]:
        """
        Search for wedding industry research with citations

        Args:
            topic: Research topic or question
            geography: Geographic focus
            time_window: Time filter

        Returns:
            Research findings with citations
        """
        # Build wedding-focused query
        query = f"""Find recent news and research about: {topic}

Focus on information relevant to wedding venue owners and operators.
Include:
- Industry statistics and data
- Market trends and forecasts
- Regulatory or policy changes
- Consumer behavior insights
- Technology and operational developments

{"Geographic focus: " + geography if geography else "Consider US market primarily."}
"""
        return self.search(query, time_window, geography, max_results=8)
