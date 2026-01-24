"""
BriteCo Brief - Agent Newsletter Generator
Backend API Server - Adapted from Venue Voice structure
"""

import os
import sys
import json
import re
import requests
import base64
from io import BytesIO
from datetime import datetime
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from dotenv import load_dotenv
from bs4 import BeautifulSoup

# SendGrid for email
try:
    import sendgrid
    from sendgrid.helpers.mail import Mail, Email, To, Content, HtmlContent
    SENDGRID_AVAILABLE = True
except ImportError:
    SENDGRID_AVAILABLE = False
    print("[WARNING] SendGrid not installed. Email functionality disabled.")

# Load environment
load_dotenv()

# Add backend to path
sys.path.append(os.path.join(os.path.dirname(__file__), 'backend'))

from integrations.openai_client import OpenAIClient
from integrations.gemini_client import GeminiClient
from integrations.claude_client import ClaudeClient
from integrations.perplexity_client import PerplexityClient
from integrations.ontraport_client import OntraportClient
from config.brand_guidelines import (
    BRAND_VOICE, NEWSLETTER_GUIDELINES, INSURANCE_NEWS_SOURCES,
    CONTENT_FILTERS, ONTRAPORT_CONFIG, TEAM_MEMBERS,
    get_style_guide_for_prompt, get_search_sources_prompt
)
from config.model_config import get_model_for_task

app = Flask(__name__, static_folder='.')
CORS(app)

# Helper function to safely print Unicode content on Windows
def safe_print(text):
    """Print text with proper encoding handling for Windows console"""
    try:
        print(text)
    except UnicodeEncodeError:
        safe_text = text.encode('ascii', errors='replace').decode('ascii')
        print(safe_text)

# Helper function to convert HTML to plain text
def html_to_plain_text(html_content):
    """Convert HTML newsletter content to plain text for Ontraport"""
    text = re.sub(r'<[^>]+>', '', html_content)
    text = text.replace('&nbsp;', ' ')
    text = text.replace('&amp;', '&')
    text = text.replace('&lt;', '<')
    text = text.replace('&gt;', '>')
    text = text.replace('&quot;', '"')
    text = text.replace('&#39;', "'")
    text = re.sub(r'\s+', ' ', text)
    text = text.strip()
    return text

# Initialize AI clients
openai_client = OpenAIClient()
gemini_client = GeminiClient()
if not gemini_client.is_available():
    print("[WARNING] Gemini image generation not available - add GOOGLE_AI_API_KEY to .env")
    print("         Get your API key at: https://aistudio.google.com/app/apikey")

# Try to initialize Claude (optional)
try:
    claude_client = ClaudeClient()
    print("[OK] Claude initialized")
except Exception as e:
    claude_client = None
    print(f"[WARNING] Claude not available: {e}")

# Initialize Perplexity client
try:
    perplexity_client = PerplexityClient()
    print("[OK] Perplexity initialized")
except Exception as e:
    perplexity_client = None
    print(f"[WARNING] Perplexity not available: {e}")

# Initialize Ontraport client
try:
    ontraport_client = OntraportClient()
    print("[OK] Ontraport initialized")
except Exception as e:
    ontraport_client = None
    print(f"[WARNING] Ontraport not available: {e}")

# ============================================================================
# ROUTES - STATIC FILES
# ============================================================================

@app.route('/')
def serve_demo():
    """Serve the main app"""
    return send_from_directory('.', 'index.html')

@app.route('/health')
def health_check():
    return jsonify({"status": "healthy", "service": "briteco-brief"})

# ============================================================================
# ROUTES - TEAM MANAGEMENT
# ============================================================================

@app.route('/api/team-members', methods=['GET'])
def get_team_members():
    """Get list of team members for preview emails"""
    return jsonify({
        "success": True,
        "team_members": TEAM_MEMBERS
    })

# ============================================================================
# HELPER FUNCTIONS - V2 RESEARCH API (Matching venue-voice pattern)
# ============================================================================

def transform_to_shared_schema(results: list, source_card: str) -> list:
    """
    Transform raw search results to shared schema for frontend.
    Matches venue-voice pattern exactly.
    """
    transformed = []
    for r in results:
        transformed.append({
            'title': r.get('title', ''),
            'headline': r.get('headline', r.get('title', '')),
            'url': r.get('url', r.get('source_url', '')),
            'publisher': r.get('publisher', ''),
            'published_at': r.get('published_date', r.get('published_at', '')),
            'snippet': r.get('snippet', r.get('description', '')),
            'industry_data': r.get('industry_data', r.get('snippet', r.get('description', ''))),
            'so_what': r.get('so_what', r.get('agent_implications', '')),
            'source_card': source_card,
            'content_type': r.get('content_type', 'news'),
            'impact': r.get('impact', 'MEDIUM'),
            'signals': r.get('signals', []),
            'signal_source': r.get('signal_source', '')
        })
    return transformed


# Keywords that indicate promotion/personnel news to filter out
PROMOTION_KEYWORDS = [
    'promoted to', 'announces promotion', 'new ceo', 'new president',
    'executive appointment', 'joins as', 'named to', 'leadership change',
    'personnel announcement', 'new hire', 'appointed as', 'steps down',
    'retires from', 'announces retirement', 'names new', 'appoints',
    'welcomes new', 'hires', 'executive team', 'board of directors appoints'
]


def filter_promotion_news(results: list) -> list:
    """Filter out promotion/personnel news from search results."""
    filtered = []
    for r in results:
        title = (r.get('title', '') + ' ' + r.get('headline', '')).lower()
        description = r.get('description', r.get('snippet', '')).lower()
        combined_text = title + ' ' + description

        is_promotion_news = any(keyword in combined_text for keyword in PROMOTION_KEYWORDS)

        if not is_promotion_news:
            filtered.append(r)
        else:
            safe_print(f"[Filter] Excluded promotion news: {r.get('title', '')[:50]}...")

    return filtered


def multi_search(queries: list, max_results: int = 4, exclude_urls: list = None) -> list:
    """
    Run multiple search queries and merge/deduplicate results.

    Uses a 3-query cascade strategy:
    1. Specific query (user's intent)
    2. Broader query (core terms)
    3. Fallback query (general topic)

    Stops early if we have enough results.
    """
    exclude_urls = exclude_urls or []
    all_results = []
    seen_urls = set()

    for i, query in enumerate(queries):
        safe_print(f"[Multi-Search] Query {i+1}/{len(queries)}: {query[:80]}...")

        try:
            results = openai_client.search_web_responses_api(
                query,
                max_results=6,  # Get extra to account for deduplication
                exclude_urls=exclude_urls + list(seen_urls)
            )

            for r in results:
                url = r.get('url', '')
                if url and url not in seen_urls:
                    all_results.append(r)
                    seen_urls.add(url)

            safe_print(f"[Multi-Search] Query {i+1} returned {len(results)} results, total unique: {len(all_results)}")

            # Stop early if we have enough
            if len(all_results) >= max_results:
                break

        except Exception as e:
            safe_print(f"[Multi-Search] Query {i+1} failed: {e}")
            continue

    return all_results[:max_results]


def search_all_signals(time_window: str = '30d', exclude_urls: list = None) -> list:
    """
    Search ALL insurance market signals simultaneously and collect results.
    Returns deduplicated results across all signal categories.
    """
    exclude_urls = exclude_urls or []

    # Signal query definitions - P&C insurance focused
    SIGNAL_QUERIES = {
        'auto_rates': 'US auto insurance rates pricing trends America recent news',
        'homeowners': 'US homeowners insurance claims premiums trends America recent',
        'commercial': 'US commercial insurance business liability market trends America',
        'catastrophe': 'US catastrophe insurance disaster claims weather events America',
        'regulations': 'US insurance regulations policy changes state commissioners America',
        'insurtech': 'US insurtech technology digital insurance innovation America recent',
        'workforce': 'US insurance agent hiring workforce trends staffing America recent',
        'claims': 'US insurance claims management litigation trends America recent'
    }

    all_results = []
    seen_urls = set(exclude_urls)

    safe_print(f"[Insight Builder] Searching all 8 insurance signals...")

    # Search each signal
    for signal, query_terms in SIGNAL_QUERIES.items():
        try:
            prompt = f"""Search for recent US news about {signal.replace('_', ' ')} in insurance.

Find articles about the United States with data points, statistics, and business impact.
Focus on P&C (property and casualty) insurance markets.
Search terms: {query_terms}

Return results with title, url, publisher, published_date, and summary with key data points."""

            results = openai_client.search_web_responses_api(prompt, max_results=4, exclude_urls=list(seen_urls))

            for r in results:
                url = r.get('url', '')
                if url and url not in seen_urls:
                    r['signal_source'] = signal  # Tag which signal found this
                    all_results.append(r)
                    seen_urls.add(url)

            safe_print(f"[Insight Builder] Signal '{signal}' returned {len(results)} results")

        except Exception as e:
            safe_print(f"[Insight Builder] Error searching signal '{signal}': {e}")
            continue

    safe_print(f"[Insight Builder] Total unique results: {len(all_results)}")
    return all_results


def analyze_industry_impact(results: list) -> list:
    """
    Use LLM to analyze each result for insurance industry impact.
    Generates newsletter-ready headlines and impact scores.
    Model selection is driven by config/vision_models.yaml task_assignments.
    """
    if not results:
        return results

    try:
        # Get model config for research enrichment task
        model_config = get_model_for_task('research_enrichment')
        model_id = model_config.get('id', 'gpt-5.2')
        max_tokens_param = model_config.get('max_tokens_param', 'max_tokens')

        safe_print(f"[Insight Builder] Analyzing {len(results)} results with {model_id}...")

        # Build context for GPT
        results_text = ""
        for i, r in enumerate(results):
            results_text += f"""
Result {i+1}:
- Signal: {r.get('signal_source', 'unknown')}
- Publisher: {r.get('publisher', '')}
- Raw title: {r.get('title', '')[:100]}
- Snippet: {r.get('description', r.get('snippet', ''))[:400]}
"""

        prompt = f"""You are analyzing news articles for an insurance agent newsletter.

For each article, determine its impact on P&C insurance agents and their clients.

Here are the articles:
{results_text}

For EACH article, provide:
1. headline: A newsletter-ready headline (5-12 words, actionable for insurance agents)
2. impact: HIGH (immediate action needed), MEDIUM (worth monitoring), or LOW (FYI only)
3. signals: Array of affected categories from [auto_rates, homeowners, commercial, catastrophe, regulations, insurtech, workforce, claims]
4. so_what: One sentence explaining what agents should do about this

Return a JSON array with exactly {len(results)} objects:
[
  {{"headline": "...", "impact": "HIGH|MEDIUM|LOW", "signals": ["..."], "so_what": "..."}},
  ...
]

Guidelines:
- HIGH impact: significant rate changes, regulatory changes, market shifts affecting client premiums
- MEDIUM impact: emerging trends, technology changes, industry forecasts
- LOW impact: general news, minor updates

Return ONLY the JSON array, no other text."""

        # Build API call with correct parameter name based on model
        api_params = {
            "model": model_id,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.3,
        }
        api_params[max_tokens_param] = 2000

        response = openai_client.client.chat.completions.create(**api_params)

        content = response.choices[0].message.content.strip()

        # Parse JSON response
        if content.startswith("```"):
            content = re.sub(r"^```[a-zA-Z]*\n", "", content)
            content = re.sub(r"\n```$", "", content).strip()

        enriched = json.loads(content)

        # Merge enriched data back into results
        for i, r in enumerate(results):
            if i < len(enriched):
                r['headline'] = enriched[i].get('headline', r.get('title', ''))
                r['impact'] = enriched[i].get('impact', 'MEDIUM')
                r['signals'] = enriched[i].get('signals', [])
                r['so_what'] = enriched[i].get('so_what', '')
                r['industry_data'] = r.get('description', r.get('snippet', ''))

        # Sort by impact: HIGH first, then MEDIUM, then LOW
        impact_order = {'HIGH': 0, 'MEDIUM': 1, 'LOW': 2}
        results.sort(key=lambda x: impact_order.get(x.get('impact', 'LOW'), 2))

        # Filter out promotion/personnel news
        results = filter_promotion_news(results)

        safe_print(f"[Insight Builder] {model_id} analysis complete - enriched {len(results)} results (after filtering)")
        return results

    except Exception as e:
        safe_print(f"[Insight Builder] Analysis error: {e} - returning original results")
        # Add default values if GPT fails
        for r in results:
            r['headline'] = r.get('title', 'Industry Update')
            r['impact'] = 'MEDIUM'
            r['signals'] = [r.get('signal_source', 'general')]
            r['so_what'] = 'Monitor this trend for potential client impact.'
        return results


def analyze_story_angles(results: list, user_query: str) -> list:
    """
    Use LLM to analyze articles and surface interesting story angles for newsletters.
    Model selection is driven by config/vision_models.yaml task_assignments.
    """
    if not results:
        return results

    try:
        # Get model config for research enrichment task
        model_config = get_model_for_task('research_enrichment')
        model_id = model_config.get('id', 'gpt-5.2')
        max_tokens_param = model_config.get('max_tokens_param', 'max_tokens')

        safe_print(f"[Source Explorer] Analyzing {len(results)} results with {model_id}...")

        # Build context for GPT
        results_text = ""
        for i, r in enumerate(results):
            results_text += f"""
Article {i+1}:
- Title: {r.get('title', '')[:100]}
- Publisher: {r.get('publisher', '')}
- Snippet: {r.get('snippet', r.get('description', ''))[:400]}
"""

        prompt = f"""You are a newsletter editor for insurance agents. The user searched for: "{user_query}"

Analyze these articles and surface the most interesting story angles for an agent newsletter.

Here are the articles:
{results_text}

For EACH article, provide:
1. story_angle: A compelling newsletter story angle (1-2 sentences) - what's the interesting hook for agents?
2. headline: A catchy headline (5-10 words) that would grab an agent's attention
3. why_it_matters: One sentence on why insurance agents should care about this
4. content_type: One of [trend, tip, news, insight, case_study]

Return a JSON array with exactly {len(results)} objects:
[
  {{"story_angle": "...", "headline": "...", "why_it_matters": "...", "content_type": "..."}},
  ...
]

Guidelines:
- Focus on actionable insights agents can use with clients
- Look for data points, trends, or tips that can be turned into content
- Headlines should be specific and engaging (not generic)
- Story angles should suggest how to write about this for agent audiences

Return ONLY the JSON array, no other text."""

        # Build API call with correct parameter name based on model
        api_params = {
            "model": model_id,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.4,
        }
        api_params[max_tokens_param] = 2000

        response = openai_client.client.chat.completions.create(**api_params)

        content = response.choices[0].message.content.strip()

        # Parse JSON response
        if content.startswith("```"):
            content = re.sub(r"^```[a-zA-Z]*\n", "", content)
            content = re.sub(r"\n```$", "", content).strip()

        enriched = json.loads(content)

        # Merge enriched data back into results
        for i, r in enumerate(results):
            if i < len(enriched):
                r['story_angle'] = enriched[i].get('story_angle', '')
                r['headline'] = enriched[i].get('headline', r.get('title', ''))
                r['why_it_matters'] = enriched[i].get('why_it_matters', '')
                r['content_type'] = enriched[i].get('content_type', 'insight')
                # Update so_what with the why_it_matters
                r['so_what'] = enriched[i].get('why_it_matters', r.get('so_what', ''))
                r['industry_data'] = r.get('snippet', r.get('description', ''))

        # Filter out promotion/personnel news
        results = filter_promotion_news(results)

        safe_print(f"[Source Explorer] {model_id} story analysis complete - enriched {len(results)} results (after filtering)")
        return results

    except Exception as e:
        safe_print(f"[Source Explorer] Analysis error: {e} - returning original results")
        # Add default values if GPT fails
        for r in results:
            r['story_angle'] = r.get('snippet', '')[:150]
            r['headline'] = r.get('title', 'Industry Update')
            r['why_it_matters'] = 'Review this article for potential newsletter content.'
            r['content_type'] = 'insight'
        return results


def enrich_results_with_llm(results: list, original_query: str) -> list:
    """
    Use LLM to generate newsletter-ready content from research results.
    Produces three-section format: headline, industry_data, so_what
    Model selection is driven by config/vision_models.yaml task_assignments.
    """
    if not results:
        return results

    try:
        # Get model config for research enrichment task
        model_config = get_model_for_task('research_enrichment')
        model_id = model_config.get('id', 'gpt-5.2')
        max_tokens_param = model_config.get('max_tokens_param', 'max_tokens')

        safe_print(f"[Enrichment] Using model: {model_id}")

        # Build a single prompt to process all results at once
        results_text = ""
        for i, r in enumerate(results):
            results_text += f"""
Result {i+1}:
- URL: {r.get('url', '')}
- Publisher: {r.get('publisher', '')}
- Raw snippet: {r.get('snippet', '')[:500]}
"""

        prompt = f"""You are analyzing research findings for an insurance agent newsletter. The user searched for: "{original_query}"

Here are research findings to transform into newsletter-ready content:
{results_text}

For EACH result, extract/generate:
1. headline: A compelling newsletter headline (5-12 words, specific and actionable)
2. industry_data: The key statistic, fact, or data point from this article (1-2 sentences). Extract actual numbers/percentages when available.
3. so_what: What should agents DO with this information? (1 actionable sentence)
4. impact: HIGH (immediate action needed), MEDIUM (worth monitoring), or LOW (FYI only)

Return a JSON array with exactly {len(results)} objects:
[
  {{"headline": "...", "industry_data": "...", "so_what": "...", "impact": "HIGH|MEDIUM|LOW"}},
  ...
]

Guidelines:
- Headlines should be specific with data when available (e.g., "Auto Rates Up 8% - Agents Should Review Client Policies")
- industry_data should contain the actual facts/stats from the article, not commentary
- so_what should be a specific action: "Review your...", "Contact clients about...", "Update your..."
- HIGH impact: significant rate changes, regulatory changes affecting client premiums
- MEDIUM impact: emerging trends, forecasts, industry shifts
- LOW impact: general news, minor updates

Return ONLY the JSON array, no other text."""

        # Build API call with correct parameter name based on model
        api_params = {
            "model": model_id,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.3,
        }
        api_params[max_tokens_param] = 2000

        response = openai_client.client.chat.completions.create(**api_params)

        content = response.choices[0].message.content.strip()

        # Parse the JSON response
        if content.startswith("```"):
            content = re.sub(r"^```[a-zA-Z]*\n", "", content)
            content = re.sub(r"\n```$", "", content).strip()

        enriched = json.loads(content)

        # Merge enriched data back into results
        for i, r in enumerate(results):
            if i < len(enriched):
                r['headline'] = enriched[i].get('headline', r.get('title', ''))
                r['title'] = r['headline']  # Use headline as title too
                r['industry_data'] = enriched[i].get('industry_data', r.get('snippet', ''))
                r['so_what'] = enriched[i].get('so_what', '')
                r['impact'] = enriched[i].get('impact', 'MEDIUM')
                # Keep snippet for backwards compatibility
                r['snippet'] = r['industry_data']

        # Sort by impact: HIGH first, then MEDIUM, then LOW
        impact_order = {'HIGH': 0, 'MEDIUM': 1, 'LOW': 2}
        results.sort(key=lambda x: impact_order.get(x.get('impact', 'LOW'), 2))

        safe_print(f"[LLM Enrichment] Successfully enriched {len(results)} results with {model_id}")
        return results

    except Exception as e:
        safe_print(f"[LLM Enrichment] Error: {e} - returning original results")
        import traceback
        traceback.print_exc()
        return results


# ============================================================================
# ROUTES - V2 RESEARCH API (Frontend Dashboard)
# ============================================================================

@app.route('/api/v2/search-perplexity', methods=['POST'])
def v2_search_perplexity():
    """
    Perplexity Research Card - uses Perplexity sonar model for research with citations
    """
    try:
        data = request.json
        query = data.get('query', 'P&C insurance industry news trends')
        time_window = data.get('time_window', '30d')  # 7d, 30d, 90d
        exclude_urls = data.get('exclude_urls', [])

        safe_print(f"\n[API v2] Perplexity Research: query='{query}', time_window={time_window}")

        # Check if Perplexity is available
        if not perplexity_client or not perplexity_client.is_available():
            return jsonify({
                'success': False,
                'error': 'Perplexity API not configured. Add PERPLEXITY_API_KEY to .env',
                'results': []
            }), 503

        # Search using Perplexity - build insurance-focused query
        search_results = perplexity_client.search(
            query=f"P&C insurance {query}",
            time_window=time_window,
            max_results=8
        )

        # Filter out excluded URLs
        if exclude_urls:
            search_results = [r for r in search_results if r.get('url') not in exclude_urls]

        # Take top 8 results for more options
        results = search_results[:8]

        # Enrich results with LLM-generated titles and agent guidance
        if results:
            safe_print(f"[API v2] Enriching {len(results)} Perplexity results with LLM...")
            results = enrich_results_with_llm(results, query)

        # Build query description for UI
        time_desc = {
            '7d': 'past week',
            '30d': 'past month',
            '90d': 'past 3 months'
        }.get(time_window, 'recent')

        return jsonify({
            'success': True,
            'results': results,
            'queries_used': [f"P&C insurance news from {time_desc}: {query}"],
            'source': 'perplexity',
            'generated_at': datetime.now().isoformat()
        })

    except Exception as e:
        safe_print(f"[API v2 ERROR] Perplexity Research: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e), 'results': []}), 500


@app.route('/api/v2/search-insights', methods=['POST'])
def v2_search_insights():
    """
    Insight Builder Card - searches ALL 8 signals and analyzes industry impact
    """
    try:
        data = request.json
        time_window = data.get('time_window', '30d')
        exclude_urls = data.get('exclude_urls', [])

        safe_print(f"\n[API v2] Insight Builder: Searching ALL 8 signals")

        # Step 1: Search all 8 signals simultaneously
        raw_results = search_all_signals(time_window=time_window, exclude_urls=exclude_urls)

        # Step 2: Analyze results with GPT for industry impact
        enriched_results = analyze_industry_impact(raw_results)

        # Step 3: Transform to shared schema and limit to top 8-12 results
        results = transform_to_shared_schema(enriched_results[:12], 'insight')

        # Merge back the enriched fields (headline, impact, signals, so_what)
        for i, result in enumerate(results):
            if i < len(enriched_results):
                enriched = enriched_results[i]
                result['headline'] = enriched.get('headline', result.get('title', ''))
                result['impact'] = enriched.get('impact', 'MEDIUM')
                result['signals'] = enriched.get('signals', [])
                result['so_what'] = enriched.get('so_what', '')
                result['industry_data'] = enriched.get('industry_data', enriched.get('description', ''))

        signals_searched = ['auto_rates', 'homeowners', 'commercial', 'catastrophe', 'regulations', 'insurtech', 'workforce', 'claims']

        return jsonify({
            'success': True,
            'results': results,
            'signals_searched': signals_searched,
            'source': 'insight',
            'generated_at': datetime.now().isoformat()
        })

    except Exception as e:
        safe_print(f"[API v2 ERROR] Insight Builder: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e), 'results': []}), 500


@app.route('/api/v2/search-sources', methods=['POST'])
def v2_search_sources():
    """
    Source Explorer Card - searches specific industry sites with 3-query cascade
    """
    try:
        data = request.json
        query = data.get('query', 'P&C insurance news')
        source_packs = data.get('source_packs', ['insurance'])  # insurance, claims, regulations
        time_window = data.get('time_window', '30d')
        exclude_urls = data.get('exclude_urls', [])

        safe_print(f"\n[API v2] Source Explorer: query='{query}', packs={source_packs}, time_window={time_window}")

        # Convert time window to human-readable for query
        time_desc = {
            '7d': 'past week',
            '30d': 'past month',
            '90d': 'past 3 months'
        }.get(time_window, 'recent')

        # Insurance industry source packs (B2B and trade publications)
        SITE_PACKS = {
            'insurance': INSURANCE_NEWS_SOURCES,  # From brand_guidelines.py
            'claims': [
                'claimsjournal.com', 'propertycasualty360.com', 'insurancejournal.com',
                'carriermanagement.com'
            ],
            'regulations': [
                'naic.org', 'insurancejournal.com', 'carriermanagement.com',
                'propertycasualty360.com'
            ],
            'technology': [
                'dig-in.com', 'insurancejournal.com', 'propertycasualty360.com',
                'carriermanagement.com'
            ]
        }

        # Collect sites from selected packs
        sites = []
        for pack in source_packs:
            sites.extend(SITE_PACKS.get(pack, []))
        sites = list(set(sites))  # Remove duplicates

        # Build site: queries with 3-query cascade
        if sites:
            # Use up to 6 sites per query for better coverage
            site_query = ' OR '.join([f'site:{s}' for s in sites[:6]])

            queries = [
                # Query 1: Site-specific with user query
                f"""Search for: ({site_query}) {query}

Find articles from the {time_desc} from these insurance industry sources.
Return results with title, url, publisher, published_date, and summary.""",

                # Query 2: Site-specific with broader topic
                f"""Search for: ({site_query}) P&C insurance news trends

Find business news from the {time_desc} about property and casualty insurance.
Return results with title, url, publisher, published_date, and summary.""",

                # Query 3: Fallback without site restriction
                f"""Search for P&C insurance industry news from trade publications.

Find articles from the {time_desc} about: {query}
Focus on business insights, trends, and industry analysis.
Return results with title, url, publisher, published_date, and summary."""
            ]
        else:
            queries = [
                f"""Search for P&C insurance industry news from the {time_desc}.
Find articles about: {query}
Return results with title, url, publisher, published_date, and summary."""
            ]

        safe_print(f"[API v2] Source Explorer using {len(sites)} sites from packs: {source_packs}")

        # Use multi-search with cascade
        search_results = multi_search(queries, max_results=8, exclude_urls=exclude_urls)

        # Transform to shared schema
        results = transform_to_shared_schema(search_results, 'explorer')

        # Enrich with GPT story angle analysis
        results = analyze_story_angles(results, query)

        # Query summaries for UI display
        query_summaries = [
            f"1. Site-specific: {query} from {', '.join(sites[:3])}...",
            "2. Broader: P&C insurance news from sites",
            "3. Fallback: insurance industry news (any source)"
        ]

        return jsonify({
            'success': True,
            'results': results,
            'queries_used': query_summaries,
            'source_packs': source_packs,
            'source': 'explorer',
            'generated_at': datetime.now().isoformat()
        })

    except Exception as e:
        safe_print(f"[API v2 ERROR] Source Explorer: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e), 'results': []}), 500


# ============================================================================
# ROUTES - BRITE SPOT
# ============================================================================

@app.route('/api/rewrite-britespot', methods=['POST'])
def rewrite_britespot():
    """Rewrite Brite Spot content using Claude in brand voice"""
    try:
        data = request.json
        content = data.get('content', '')
        tone = data.get('tone', 'informative')

        if not content:
            return jsonify({'success': False, 'error': 'Content required'}), 400

        print(f"\n[API] Rewriting Brite Spot content ({tone} tone)...")

        if not claude_client:
            return jsonify({'success': False, 'error': 'Claude client not available'}), 500

        tone_instructions = {
            'exciting': 'Make it energetic and exciting with action words',
            'informative': 'Keep it clear, factual, and professional',
            'professional': 'Use formal business language and tone'
        }

        prompt = f"""Rewrite this BriteCo company update for our agent newsletter "The Brite Spot" section.

ORIGINAL CONTENT:
{content}

REQUIREMENTS:
- Maximum 100 words
- {tone_instructions.get(tone, 'Professional but approachable')}
- Focus on value to independent insurance agents
- Include a subtle call to action
- BriteCo brand voice: professional, knowledgeable, supportive

Output ONLY the rewritten content, no labels or explanations."""

        result = claude_client.generate_content(
            prompt=prompt,
            model="claude-opus-4-5-20251101",
            temperature=0.4,
            max_tokens=200
        )

        return jsonify({
            'success': True,
            'rewritten': result['content'].strip(),
            'original': content,
            'tone': tone
        })

    except Exception as e:
        print(f"[API ERROR] Brite Spot rewrite: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


# ============================================================================
# ROUTES - INSURNEWS SPOTLIGHT (Multi-Source)
# ============================================================================

@app.route('/api/search-spotlight-articles', methods=['POST'])
def search_spotlight_articles():
    """Search for InsurNews Spotlight articles from curated insurance sources"""
    try:
        data = request.json
        query = data.get('query', 'P&C insurance news')
        time_window = data.get('time_window', '30d')
        exclude_urls = data.get('exclude_urls', [])

        print(f"\n[API] Searching Spotlight articles from curated sources: {query}")

        all_results = []
        seen_urls = set(exclude_urls)

        # Build site filter from curated insurance sources
        site_filter = ' OR '.join([f'site:{s}' for s in INSURANCE_NEWS_SOURCES])

        # Search 1: Main query with curated sources (OpenAI)
        try:
            main_query = f"{query} ({site_filter})"
            main_results = openai_client.search_web(
                query=main_query,
                exclude_urls=list(seen_urls),
                max_results=8
            )
            for r in main_results:
                url = r.get('url', '')
                if url and url not in seen_urls:
                    seen_urls.add(url)
                    all_results.append({
                        'title': r.get('title', ''),
                        'headline': r.get('title', ''),
                        'url': url,
                        'publisher': r.get('publisher', ''),
                        'snippet': r.get('snippet', r.get('description', '')),
                        'industry_data': r.get('snippet', ''),
                        'so_what': 'Review for InsurNews Spotlight feature story',
                        'source_card': 'curated'
                    })
            print(f"  - Found {len(main_results)} from curated sources")
        except Exception as e:
            print(f"  - Curated search error: {e}")

        # Search 2: Perplexity for research-backed results (if available)
        if perplexity_client and perplexity_client.is_available():
            try:
                perplexity_results = perplexity_client.search(
                    query=f"P&C insurance {query}",
                    time_window=time_window,
                    max_results=6
                )
                for r in perplexity_results:
                    url = r.get('url', '')
                    if url and url not in seen_urls:
                        seen_urls.add(url)
                        all_results.append({
                            'title': r.get('title', ''),
                            'headline': r.get('title', ''),
                            'url': url,
                            'publisher': r.get('publisher', ''),
                            'snippet': r.get('snippet', ''),
                            'industry_data': r.get('snippet', ''),
                            'so_what': r.get('agent_implications', 'Research-backed insight'),
                            'source_card': 'perplexity'
                        })
                print(f"  - Found {len(perplexity_results)} from Perplexity")
            except Exception as e:
                print(f"  - Perplexity search error: {e}")

        # Search 3: Industry signals/insights
        try:
            signals = ['insurance rates trends', 'claims news', 'insurance regulations', 'insurtech news']
            for signal in signals[:2]:
                signal_query = f"{signal} site:insurancejournal.com OR site:propertycasualty360.com"
                signal_results = openai_client.search_web(
                    query=signal_query,
                    exclude_urls=list(seen_urls),
                    max_results=3
                )
                for r in signal_results:
                    url = r.get('url', '')
                    if url and url not in seen_urls:
                        seen_urls.add(url)
                        all_results.append({
                            'title': r.get('title', ''),
                            'headline': r.get('title', ''),
                            'url': url,
                            'publisher': r.get('publisher', ''),
                            'snippet': r.get('snippet', r.get('description', '')),
                            'industry_data': r.get('snippet', ''),
                            'so_what': f'Industry signal: {signal}',
                            'source_card': 'insights'
                        })
            print(f"  - Added industry signal results")
        except Exception as e:
            print(f"  - Industry signals error: {e}")

        print(f"[API] Total Spotlight articles found: {len(all_results)}")

        return jsonify({
            'success': True,
            'results': all_results[:15],  # Cap at 15 results
            'sources_searched': ['curated_insurance', 'perplexity', 'industry_signals'],
            'generated_at': datetime.now().isoformat()
        })

    except Exception as e:
        print(f"[API ERROR] Spotlight article search: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e), 'results': []}), 500


@app.route('/api/generate-spotlight', methods=['POST'])
def generate_spotlight():
    """Generate InsurNews Spotlight from multiple source articles"""
    try:
        data = request.json
        articles = data.get('articles', [])
        month = data.get('month', 'january')

        if len(articles) < 3:
            return jsonify({'success': False, 'error': 'At least 3 articles required'}), 400

        print(f"\n[API] Generating InsurNews Spotlight from {len(articles)} articles...")

        if not claude_client:
            return jsonify({'success': False, 'error': 'Claude client not available'}), 500

        # Build article summaries for the prompt
        article_summaries = ""
        sources = []
        for i, article in enumerate(articles, 1):
            article_summaries += f"""
ARTICLE {i}:
Title: {article.get('title', article.get('headline', 'Unknown'))}
Source: {article.get('publisher', 'Unknown')}
URL: {article.get('url', '')}
Summary: {article.get('snippet', article.get('industry_data', ''))}
"""
            sources.append({
                'title': article.get('title', article.get('headline', '')),
                'url': article.get('url', ''),
                'publisher': article.get('publisher', '')
            })

        prompt = f"""You are writing the "InsurNews Spotlight" section for BriteCo Brief, a newsletter for independent insurance agents.

Analyze these {len(articles)} related articles and create a comprehensive, in-depth feature story:

{article_summaries}

Write a detailed spotlight article with:
- First line: A compelling headline/subheader (max 15 words)
- Then 4-5 paragraphs covering the story (what's happening, why it matters, industry impact, implications for agents)
- Each paragraph should be 3-5 sentences with specific data and statistics from the sources
- End with "AGENT TAKEAWAY:" followed by 3-4 bullet points of actionable insights

Target: 500-600 words. Be thorough and factual.

Output as plain text - headline on first line, then paragraphs, then agent takeaway section at the end."""

        result = claude_client.generate_content(
            prompt=prompt,
            model="claude-opus-4-5-20251101",
            temperature=0.3,
            max_tokens=2000
        )

        content_text = result['content'].strip()
        print(f"[API] Spotlight response length: {len(content_text)}")

        # Parse plain text response: first line is subheader, rest is body
        lines = content_text.split('\n', 1)
        subheader = lines[0].strip().strip('#').strip() if lines else 'Insurance Industry Update'
        body_text = lines[1].strip() if len(lines) > 1 else content_text

        # Extract agent takeaway if present
        agent_takeaway = ''
        takeaway_markers = ['AGENT TAKEAWAY:', 'Agent Takeaway:', 'TAKEAWAY:', 'Takeaway:']
        for marker in takeaway_markers:
            if marker in body_text:
                parts = body_text.split(marker, 1)
                body_text = parts[0].strip()
                agent_takeaway = parts[1].strip() if len(parts) > 1 else ''
                break

        # Build simple structure - body as single text block
        spotlight_content = {
            'subheader': subheader,
            'body': body_text,
            'agent_takeaway': agent_takeaway or 'Review these developments and consider their impact on your clients.'
        }

        spotlight_content['sources'] = sources

        print(f"[API] Spotlight generated: {spotlight_content.get('subheader', 'No title')}")

        return jsonify({
            'success': True,
            'content': spotlight_content,
            'generated_at': datetime.now().isoformat()
        })

    except Exception as e:
        print(f"[API ERROR] Spotlight generation: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


# ============================================================================
# ROUTES - FETCH ARTICLE FROM URL
# ============================================================================

@app.route('/api/fetch-article', methods=['POST'])
def fetch_article():
    """Fetch and analyze an article from a user-provided URL using web scraping + OpenAI"""
    try:
        data = request.json
        url = data.get('url', '').strip()
        section = data.get('section', 'general')  # claims, roundup, spotlight, tips

        if not url:
            return jsonify({'success': False, 'error': 'URL is required'}), 400

        print(f"\n[API] Fetching article from URL: {url}")
        print(f"  - Section: {section}")

        # Step 1: Fetch the webpage content using requests
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
        }

        try:
            response = requests.get(url, headers=headers, timeout=15)
            response.raise_for_status()
        except requests.exceptions.RequestException as e:
            print(f"[API] Failed to fetch URL: {str(e)}")
            return jsonify({'success': False, 'error': f'Failed to fetch article: {str(e)}'}), 400

        # Step 2: Parse HTML with BeautifulSoup
        soup = BeautifulSoup(response.text, 'html.parser')

        # Extract title
        title = ''
        if soup.title:
            title = soup.title.string or ''
        # Try og:title if available
        og_title = soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title = og_title.get('content')

        # Extract meta description
        meta_desc = ''
        meta_tag = soup.find('meta', attrs={'name': 'description'})
        if meta_tag and meta_tag.get('content'):
            meta_desc = meta_tag.get('content')
        # Try og:description
        og_desc = soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            meta_desc = og_desc.get('content')

        # Extract publisher from og:site_name or domain
        publisher = ''
        og_site = soup.find('meta', property='og:site_name')
        if og_site and og_site.get('content'):
            publisher = og_site.get('content')
        else:
            # Extract from domain
            from urllib.parse import urlparse
            parsed = urlparse(url)
            publisher = parsed.netloc.replace('www.', '')

        # Extract article body text
        # Remove script, style, nav, footer elements
        for element in soup(['script', 'style', 'nav', 'footer', 'header', 'aside', 'iframe']):
            element.decompose()

        # Try to find article content
        article_text = ''
        article = soup.find('article')
        if article:
            article_text = article.get_text(separator=' ', strip=True)
        else:
            # Fallback to main content area or body
            main = soup.find('main') or soup.find('div', class_=re.compile(r'content|article|post|story', re.I))
            if main:
                article_text = main.get_text(separator=' ', strip=True)
            else:
                article_text = soup.body.get_text(separator=' ', strip=True) if soup.body else ''

        # Clean up whitespace
        article_text = re.sub(r'\s+', ' ', article_text).strip()
        # Limit to first 5000 chars to avoid token limits
        article_text = article_text[:5000]

        print(f"[API] Scraped {len(article_text)} chars from page")
        print(f"  - Title: {title[:60]}...")

        # Step 3: Use OpenAI to analyze the scraped content
        analyze_prompt = f"""Analyze this article content and extract key information for an insurance agent newsletter.

ARTICLE TITLE: {title}

ARTICLE CONTENT:
{article_text}

Extract and return a JSON object with:
{{
    "title": "A concise, engaging headline for this article (use the original title if good, or improve it)",
    "description": "A 2-3 sentence summary of the article's main points",
    "publisher": "{publisher}",
    "snippet": "A longer summary (4-5 sentences) with key facts and data points",
    "industry_data": "Any specific statistics, percentages, or data mentioned (or empty string if none)",
    "agent_implications": "How this news affects independent insurance agents (2-3 sentences)",
    "content_type": "news" | "tip" | "trend" | "case_study" | "insight"
}}

Focus on P&C insurance relevance. If the article is not insurance-related, still extract the information but note that in the description."""

        result = openai_client.generate_content(
            prompt=analyze_prompt,
            model="gpt-4.1-2025-04-14",
            temperature=0.3,
            max_tokens=800
        )

        # Parse the JSON response
        content_text = result['content'].strip()

        # Remove markdown code blocks if present
        if content_text.startswith('```'):
            content_text = content_text.split('```')[1]
            if content_text.startswith('json'):
                content_text = content_text[4:]
            content_text = content_text.strip()

        try:
            article_data = json.loads(content_text)
        except json.JSONDecodeError:
            # Fallback if parsing fails
            article_data = {
                'title': title or 'Article from ' + url,
                'description': meta_desc or content_text[:200],
                'publisher': publisher or 'External Source',
                'snippet': content_text,
                'industry_data': '',
                'agent_implications': '',
                'content_type': 'news'
            }

        # Add the URL to the result
        article_data['url'] = url
        article_data['source_url'] = url
        article_data['headline'] = article_data.get('title', '')
        article_data['so_what'] = article_data.get('agent_implications', '')

        print(f"[API] Article analyzed: {article_data.get('title', 'Unknown')}")

        return jsonify({
            'success': True,
            'article': article_data,
            'generated_at': datetime.now().isoformat()
        })

    except Exception as e:
        print(f"[API ERROR] Fetch article failed: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


# ============================================================================
# ROUTES - ARTICLE SEARCH (Legacy)
# ============================================================================

@app.route('/api/search-news', methods=['POST'])
def search_news():
    """Search for P&C insurance news articles using OpenAI Responses API"""
    try:
        data = request.json
        month = data.get('month', 'january')
        exclude_urls = data.get('exclude_urls', [])

        print(f"\n[API] Searching for insurance news (month: {month})...")

        # Build search query for P&C insurance news
        sources_list = ' OR '.join([f'site:{s}' for s in INSURANCE_NEWS_SOURCES])
        search_query = f"P&C insurance news {month} 2026 ({sources_list})"

        try:
            search_results = openai_client.search_web(
                query=search_query,
                exclude_urls=exclude_urls,
                max_results=15
            )

            # Transform for frontend compatibility
            for result in search_results:
                result['source_url'] = result.get('url', '')

            articles = search_results[:15]

            if len(articles) > 0:
                print(f"[API] Found {len(articles)} insurance news articles")
                return jsonify({
                    'success': True,
                    'articles': articles,
                    'source': 'openai_responses_api',
                    'generated_at': datetime.now().isoformat()
                })
            else:
                return jsonify({
                    'success': False,
                    'error': 'No articles found from web search',
                    'articles': [],
                    'generated_at': datetime.now().isoformat()
                }), 500

        except Exception as e:
            print(f"[API ERROR] Search failed: {e}")
            import traceback
            traceback.print_exc()
            return jsonify({
                'success': False,
                'error': str(e),
                'articles': [],
                'generated_at': datetime.now().isoformat()
            }), 500

    except Exception as e:
        print(f"[API ERROR] {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/search-claims', methods=['POST'])
def search_claims():
    """Search for interesting/curious claims stories - unusual, strange, noteworthy insurance cases"""
    try:
        data = request.json
        month = data.get('month', 'january')
        exclude_urls = data.get('exclude_urls', [])

        print(f"\n[API] Searching for curious claims stories (month: {month})...")

        # Multiple search queries to find interesting claims stories
        # Focus on specific types of stories that make good "Curious Claims" content
        CLAIMS_SEARCH_QUERIES = [
            # Unusual/strange claims
            '"unusual claim" OR "strange claim" OR "bizarre claim" insurance',
            '"insurance claim" lawsuit settlement verdict',
            'insurance fraud case caught convicted',
            '"filed a claim" "insurance company" story',
            # Specific incident types that make good stories
            'homeowner insurance claim damage unusual',
            'auto insurance claim accident story',
            'liability insurance claim lawsuit ruling',
            # Claims Journal specific searches (great source for claims stories)
            'site:claimsjournal.com claim story',
            'site:claimsjournal.com insurance lawsuit verdict',
            # Court cases and settlements
            '"insurance dispute" "court ruled" OR settlement',
            'property damage claim "insurance paid" OR denied'
        ]

        all_results = []
        seen_urls = set(exclude_urls)

        try:
            # Try each search query until we have enough results
            for query in CLAIMS_SEARCH_QUERIES:
                if len(all_results) >= 12:
                    break

                safe_print(f"[Claims Search] Trying query: {query[:60]}...")

                try:
                    search_results = openai_client.search_web(
                        query=query,
                        exclude_urls=list(seen_urls),
                        max_results=6
                    )

                    for result in search_results:
                        url = result.get('url', '')
                        if url and url not in seen_urls:
                            result['source_url'] = url
                            all_results.append(result)
                            seen_urls.add(url)

                except Exception as e:
                    safe_print(f"[Claims Search] Query failed: {e}")
                    continue

            # Filter out promotion/personnel news
            all_results = filter_promotion_news(all_results)

            claims = all_results[:15]

            if len(claims) > 0:
                print(f"[API] Found {len(claims)} claims stories")
                return jsonify({
                    'success': True,
                    'claims': claims,
                    'source': 'openai_responses_api_multi',
                    'generated_at': datetime.now().isoformat()
                })
            else:
                return jsonify({
                    'success': False,
                    'error': 'No claims stories found',
                    'claims': [],
                    'generated_at': datetime.now().isoformat()
                }), 500

        except Exception as e:
            print(f"[API ERROR] Claims search failed: {e}")
            return jsonify({
                'success': False,
                'error': str(e),
                'claims': [],
                'generated_at': datetime.now().isoformat()
            }), 500

    except Exception as e:
        print(f"[API ERROR] {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/search-tips', methods=['POST'])
def search_tips():
    """Search for agent tips and advice articles"""
    try:
        data = request.json
        month = data.get('month', 'january')
        exclude_urls = data.get('exclude_urls', [])

        print(f"\n[API] Searching for agent tips (month: {month})...")

        # Build search query for agent tips
        search_query = f"insurance agent tips sales strategies client retention independent agent advice"

        try:
            search_results = openai_client.search_web(
                query=search_query,
                exclude_urls=exclude_urls,
                max_results=15
            )

            for result in search_results:
                result['source_url'] = result.get('url', '')

            tips = search_results[:15]

            if len(tips) > 0:
                print(f"[API] Found {len(tips)} agent tip articles")
                return jsonify({
                    'success': True,
                    'tips': tips,
                    'source': 'openai_responses_api',
                    'generated_at': datetime.now().isoformat()
                })
            else:
                return jsonify({
                    'success': False,
                    'error': 'No tips found',
                    'tips': [],
                    'generated_at': datetime.now().isoformat()
                }), 500

        except Exception as e:
            print(f"[API ERROR] Tips search failed: {e}")
            return jsonify({
                'success': False,
                'error': str(e),
                'tips': [],
                'generated_at': datetime.now().isoformat()
            }), 500

    except Exception as e:
        print(f"[API ERROR] {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/search-roundup', methods=['POST'])
def search_roundup():
    """Search for news roundup articles (5 bullet points)"""
    try:
        data = request.json
        month = data.get('month', 'january')
        exclude_urls = data.get('exclude_urls', [])

        print(f"\n[API] Searching for news roundup articles (month: {month})...")

        # Build search query for general P&C news
        sources_list = ' OR '.join([f'site:{s}' for s in INSURANCE_NEWS_SOURCES])
        search_query = f"property casualty insurance news trends regulations {month} 2026 ({sources_list})"

        try:
            search_results = openai_client.search_web(
                query=search_query,
                exclude_urls=exclude_urls,
                max_results=15
            )

            for result in search_results:
                result['source_url'] = result.get('url', '')

            roundup = search_results[:15]

            if len(roundup) > 0:
                print(f"[API] Found {len(roundup)} roundup articles")
                return jsonify({
                    'success': True,
                    'articles': roundup,
                    'source': 'openai_responses_api',
                    'generated_at': datetime.now().isoformat()
                })
            else:
                return jsonify({
                    'success': False,
                    'error': 'No roundup articles found',
                    'articles': [],
                    'generated_at': datetime.now().isoformat()
                }), 500

        except Exception as e:
            print(f"[API ERROR] Roundup search failed: {e}")
            return jsonify({
                'success': False,
                'error': str(e),
                'articles': [],
                'generated_at': datetime.now().isoformat()
            }), 500

    except Exception as e:
        print(f"[API ERROR] {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/search-spotlight', methods=['POST'])
def search_spotlight():
    """Search for major insurance news for InsurNews Spotlight"""
    try:
        data = request.json
        month = data.get('month', 'january')
        exclude_urls = data.get('exclude_urls', [])

        print(f"\n[API] Searching for spotlight topics (month: {month})...")

        # Build search query for major insurance news
        sources_list = ' OR '.join([f'site:{s}' for s in INSURANCE_NEWS_SOURCES])
        search_query = f"major insurance news breaking P&C industry {month} 2026 ({sources_list})"

        try:
            search_results = openai_client.search_web(
                query=search_query,
                exclude_urls=exclude_urls,
                max_results=10
            )

            for result in search_results:
                result['source_url'] = result.get('url', '')

            spotlight = search_results[:10]

            if len(spotlight) > 0:
                print(f"[API] Found {len(spotlight)} spotlight topics")
                return jsonify({
                    'success': True,
                    'articles': spotlight,
                    'source': 'openai_responses_api',
                    'generated_at': datetime.now().isoformat()
                })
            else:
                return jsonify({
                    'success': False,
                    'error': 'No spotlight topics found',
                    'articles': [],
                    'generated_at': datetime.now().isoformat()
                }), 500

        except Exception as e:
            print(f"[API ERROR] Spotlight search failed: {e}")
            return jsonify({
                'success': False,
                'error': str(e),
                'articles': [],
                'generated_at': datetime.now().isoformat()
            }), 500

    except Exception as e:
        print(f"[API ERROR] {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

# ============================================================================
# ROUTES - RESEARCH ARTICLES
# ============================================================================

@app.route('/api/research-articles', methods=['POST'])
def research_articles():
    """
    Research selected articles and produce detailed summaries using GPT.
    """
    try:
        data = request.json
        curious_claims_topic = data.get('curious_claims_topic')
        roundup_topics = data.get('roundup_topics', [])  # List of 5 articles
        spotlight_content = data.get('spotlight_content')  # Pre-generated spotlight content from Step 2B
        agent_tips_topics = data.get('agent_tips_topics', [])  # List of 5 tips

        print(f"\n[API] Researching selected articles...")

        research_results = {}

        # Research Curious Claims (~350-400 words, storytelling narrative)
        if curious_claims_topic:
            safe_print(f"  - Researching Curious Claims: {curious_claims_topic.get('title', 'Unknown')}")
            claims_prompt = f"""You are a master storyteller writing for BriteCo Brief, an insurance newsletter for independent agents.

Article: {curious_claims_topic.get('title', 'Unknown')}
Source: {curious_claims_topic.get('url', 'N/A')}
Initial Summary: {curious_claims_topic.get('description', '')}

Write an engaging STORY about this claims case using this structure:

1. HOOK (1-2 sentences)
Start with an attention-grabbing opening that draws readers in. Make it dramatic or intriguing.

2. THE SETUP (2-3 sentences)
Set the scene. Who was involved? What was the situation before the claim?

3. THE INCIDENT (3-4 sentences)
What happened? Describe the unusual claim event with vivid details. Paint a picture.

4. THE TWIST OR COMPLICATION (2-3 sentences)
What made this claim interesting or challenging? Was there something unexpected?

5. THE RESOLUTION (2-3 sentences)
How was it resolved? What did the insurance cover or not cover?

6. AGENT TAKEAWAY (2-3 sentences)
End with a clear lesson for insurance agents. How can they use this story with clients?

STYLE REQUIREMENTS:
- Write in a conversational, engaging tone
- Use short paragraphs (2-3 sentences each)
- Make it feel like a story, not a report
- Include a memorable detail or quote if possible
- Target: 350-400 words total

Output the complete story as flowing prose, not as labeled sections."""

            claims_research = claude_client.generate_content(
                prompt=claims_prompt,
                model="claude-opus-4-5-20251101",
                temperature=0.5,
                max_tokens=800
            )
            research_results['curious_claims'] = claims_research['content']
            print(f"    Curious Claims research: {len(claims_research['content'].split())} words")

        # Research News Roundup (5 bullet points, headline-style with hyperlinks)
        if roundup_topics and len(roundup_topics) > 0:
            safe_print(f"  - Researching {len(roundup_topics)} roundup articles...")
            roundup_items = []
            for topic in roundup_topics[:5]:
                safe_print(f"    - {topic.get('title', 'Unknown')[:50]}...")
                source_name = topic.get('publisher', 'Source')
                url = topic.get('url', '#')

                roundup_prompt = f"""Create a headline-style news bullet for this insurance story (~25-30 words).

Article: {topic.get('title', 'Unknown')}
Summary: {topic.get('description', '')}
Source: {source_name}

FORMAT REQUIREMENTS:
- Start with a catchy, attention-grabbing phrase
- Include the key news point
- End with a hyperlink: [Source Name]({url})
- Total ~25-30 words

EXAMPLE FORMAT:
"Rate hikes hit California hard, and [Insurance Journal](https://insurancejournal.com/article) reports State Farm is leading the charge with a 15% increase affecting 2 million policyholders."

Another example:
"Big changes for commercial auto, as [PropertyCasualty360](https://propertycasualty360.com/article) reveals new underwriting guidelines that could reshape fleet coverage nationwide."

Output ONLY the bullet text with the embedded hyperlink, nothing else."""

                roundup_result = claude_client.generate_content(
                    prompt=roundup_prompt,
                    model="claude-opus-4-5-20251101",
                    temperature=0.3,
                    max_tokens=150
                )
                roundup_items.append({
                    'summary': roundup_result['content'].strip(),
                    'url': url,
                    'source': source_name
                })
            research_results['roundup'] = roundup_items
            print(f"    Roundup research complete: {len(roundup_items)} items")

        # Use pre-generated InsurNews Spotlight content from Step 2B
        if spotlight_content:
            safe_print(f"  - Using pre-generated Spotlight: {spotlight_content.get('subheader', 'Unknown')}")
            # Pass through the pre-generated spotlight content directly
            research_results['spotlight'] = spotlight_content
            print(f"    Spotlight content ready: {spotlight_content.get('subheader', 'No title')}")

        # Research Agent Advantage Tips (1 article generates intro + 5 tips)
        # Frontend now passes a single article object, not an array
        if agent_tips_topics:
            # Handle both old array format and new single object format
            if isinstance(agent_tips_topics, list):
                topic = agent_tips_topics[0] if len(agent_tips_topics) > 0 else None
            else:
                topic = agent_tips_topics

            if topic:
                safe_print(f"  - Generating Agent Advantage from: {topic.get('title', 'Unknown')[:50]}...")

                tips_prompt = f"""Create the "Agent Advantage" section for an insurance agent newsletter based on this article.

ARTICLE TO DRAW FROM:
Title: {topic.get('title', 'Unknown')}
Summary: {topic.get('description', topic.get('snippet', ''))}
Source: {topic.get('publisher', 'Industry Source')}

FORMAT REQUIREMENTS:
1. Start with an INTRO PARAGRAPH (2-3 sentences, ~40 words) that sets up the topic and explains why it matters to agents
2. Then provide EXACTLY 5 numbered tips, each with:
   - A BOLD MINI-TITLE (up to 10 words, action-oriented)
   - 1-3 supporting sentences explaining the tip (~30-40 words per tip)
3. Focus on sales, retention, or operations improvements

OUTPUT FORMAT (use this exact structure):
[INTRO]
Your intro paragraph here (2-3 sentences).

[TIPS]
1. **Bold Mini-Title Here**
Supporting sentences explaining this tip and how agents can apply it.

2. **Another Bold Mini-Title**
More supporting detail for this actionable advice.

3. **Third Tip Title**
Explanation and practical application.

4. **Fourth Tip Title**
Supporting detail.

5. **Fifth Tip Title**
Final piece of advice.

EXAMPLE:
[INTRO]
With auto rates climbing nationwide, agents have a unique opportunity to differentiate themselves. Here's how to turn rate conversations into retention wins.

[TIPS]
1. **Lead With Transparency on Rate Changes**
Don't wait for clients to call asking about increases. Proactively reach out to explain what's happening in the market and why.

2. **Bundle for Better Value**
Combine auto with home or umbrella policies. Bundling can offset rate increases and makes clients stickier.

(etc.)

Output ONLY the intro and tips in this format, nothing else."""

                tips_result = claude_client.generate_content(
                    prompt=tips_prompt,
                    model="claude-opus-4-5-20251101",
                    temperature=0.4,
                    max_tokens=800
                )

                # Parse the response into intro and tips
                content = tips_result['content'].strip()
                intro = ""
                tips_items = []

                # Extract intro section
                if '[INTRO]' in content:
                    parts = content.split('[TIPS]')
                    intro_part = parts[0].replace('[INTRO]', '').strip()
                    intro = intro_part
                    tips_part = parts[1].strip() if len(parts) > 1 else ""
                else:
                    # Fallback: first paragraph is intro
                    lines = content.split('\n\n')
                    intro = lines[0] if lines else ""
                    tips_part = '\n\n'.join(lines[1:]) if len(lines) > 1 else content

                # Parse individual tips (look for numbered items with bold titles)
                import re
                tip_pattern = r'\d+\.\s*\*\*(.+?)\*\*\s*\n?(.+?)(?=\n\d+\.|$)'
                matches = re.findall(tip_pattern, tips_part, re.DOTALL)

                for title, body in matches[:5]:
                    tips_items.append({
                        'title': title.strip(),
                        'tip': body.strip(),
                        'source_url': topic.get('url', '')
                    })

                # If parsing failed, treat whole content as tips
                if not tips_items:
                    tips_items.append({
                        'tip': content,
                        'source_url': topic.get('url', '')
                    })

                research_results['agent_tips'] = {
                    'intro': intro,
                    'tips': tips_items,
                    'source_url': topic.get('url', ''),
                    'source_title': topic.get('title', '')
                }
                print(f"    Agent Advantage complete: intro + {len(tips_items)} tips")

        print(f"[API] Research complete")

        return jsonify({
            'success': True,
            'research': research_results,
            'generated_at': datetime.now().isoformat()
        })

    except Exception as e:
        print(f"[API ERROR] Research failed: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500

# ============================================================================
# ROUTES - CONTENT GENERATION
# ============================================================================

@app.route('/api/generate-content', methods=['POST'])
def generate_content():
    """
    Generate newsletter content using Claude Opus 4.5.
    """
    try:
        data = request.json
        month = data.get('month', 'january')
        research = data.get('research')
        brite_spot_topic = data.get('brite_spot_topic', '')
        intro_content = data.get('intro_content', '')

        if not research:
            return jsonify({'success': False, 'error': 'Research data required'}), 400

        print(f"\n[API] Generating content for {month} using Claude Opus 4.5...")

        if not claude_client:
            raise ValueError("Claude client not available for writing")

        sections = {}
        style_guide = get_style_guide_for_prompt()

        # Generate Introduction (1-4 sentences, ~75 words)
        # Use provided intro if available, otherwise generate
        if intro_content:
            print("  - Using provided intro content...")
            sections['introduction'] = intro_content
        else:
            print("  - Generating Introduction...")
            intro_prompt = f"""You are the copywriter for BriteCo Brief, a newsletter for independent insurance agents.

Write a brief, welcoming introduction for the {month.capitalize()} edition.

Requirements:
- 1-4 sentences
- Maximum 75 words
- Welcoming tone
- Reference the month/season
- Hint at what's inside this edition

{style_guide}

Output ONLY the introduction text, no labels or formatting."""

            intro_result = claude_client.generate_content(
                prompt=intro_prompt,
                model="claude-opus-4-5-20251101",
                temperature=0.5,
                max_tokens=150
            )
            sections['introduction'] = intro_result['content'].strip()

        # Generate Brite Spot (max 100 words)
        if brite_spot_topic:
            print("  - Generating Brite Spot...")
            brite_spot_prompt = f"""You are the copywriter for BriteCo Brief newsletter.

Write the "Brite Spot" section about: {brite_spot_topic}

Requirements:
- Maximum 100 words
- Exciting, informative tone
- Focus on new BriteCo features or company news
- Include a subtle call to action

{style_guide}

Output ONLY the Brite Spot text, no title or labels."""

            brite_spot_result = claude_client.generate_content(
                prompt=brite_spot_prompt,
                model="claude-opus-4-5-20251101",
                temperature=0.4,
                max_tokens=200
            )
            sections['brite_spot'] = brite_spot_result['content'].strip()

        # Generate Curious Claims from research
        if research.get('curious_claims'):
            print("  - Writing Curious Claims section...")
            claims_prompt = f"""You are the copywriter for BriteCo Brief newsletter.

## RESEARCH BRIEFING
{research['curious_claims']}

Write the "Curious Claims" section based on this research.

Requirements:
- 2-3 short paragraphs
- Maximum 200 words
- Engaging, storytelling tone
- End with a takeaway for agents

{style_guide}

Output ONLY the section text, no title or labels."""

            claims_result = claude_client.generate_content(
                prompt=claims_prompt,
                model="claude-opus-4-5-20251101",
                temperature=0.4,
                max_tokens=400
            )
            sections['curious_claims'] = claims_result['content'].strip()

        # News Roundup is already formatted as bullet points from research
        if research.get('roundup'):
            sections['roundup'] = research['roundup']

        # Use pre-generated InsurNews Spotlight content (already written in Step 2B)
        # Keep the object structure for frontend to display properly
        if research.get('spotlight'):
            print("  - Formatting InsurNews Spotlight section...")
            spotlight_data = research['spotlight']

            if isinstance(spotlight_data, dict):
                # Keep the full object structure for frontend display
                sections['spotlight'] = spotlight_data
                sections['spotlight_subheader'] = spotlight_data.get('subheader', '')
                sections['spotlight_sources'] = spotlight_data.get('sources', [])
            else:
                # Fallback if it's already a string - wrap in object structure
                sections['spotlight'] = {
                    'subheader': 'Industry Spotlight',
                    'h3s': [{'title': 'Overview', 'body': str(spotlight_data)}]
                }

        # Agent Advantage tips are already formatted from research
        if research.get('agent_tips'):
            sections['agent_tips'] = research['agent_tips']

        print(f"[API] Content generated successfully")

        return jsonify({
            'success': True,
            'content': sections,
            'generated_at': datetime.now().isoformat()
        })

    except Exception as e:
        print(f"[API ERROR] Content generation failed: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500

# ============================================================================
# ROUTES - IMAGE GENERATION
# ============================================================================

@app.route('/api/generate-image-prompts', methods=['POST'])
def generate_image_prompts():
    """Generate image prompts for newsletter sections"""
    try:
        data = request.json
        sections = data.get('sections', {})
        month = data.get('month', 'january')

        print(f"\n[API] Generating image prompts for {len(sections)} sections...")

        prompts = {}

        for section_name, section_data in sections.items():
            print(f"  - Creating image prompt for {section_name}")

            title = section_data.get('title', '')
            content = section_data.get('content', '')[:400]

            prompt_request = f"""Create a text-to-image prompt for an insurance newsletter illustration.

Section: {section_name}
Title: "{title}"
Content: "{content}..."

Requirements:
- Professional, clean aesthetic
- Blue/teal color palette (BriteCo brand colors)
- No text in the image
- Suitable for email newsletter
- Modern, digital style

Output ONLY the image generation prompt, nothing else."""

            prompt_result = claude_client.generate_content(
                prompt=prompt_request,
                model="claude-opus-4-5-20251101",
                temperature=0.5,
                max_tokens=150
            )

            prompts[section_name] = {
                'prompt': prompt_result['content'].strip(),
                'title': title
            }

        print(f"[API] Generated {len(prompts)} image prompts")

        return jsonify({
            'success': True,
            'prompts': prompts,
            'generated_at': datetime.now().isoformat()
        })

    except Exception as e:
        print(f"[API ERROR] Image prompt generation failed: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/generate-image', methods=['POST'])
def generate_image():
    """Generate an image using Gemini"""
    try:
        data = request.json
        prompt = data.get('prompt', '')
        section = data.get('section', 'general')

        if not prompt:
            return jsonify({'success': False, 'error': 'Prompt required'}), 400

        print(f"\n[API] Generating image for {section}...")
        safe_print(f"  Prompt: {prompt[:100]}...")

        # Generate image using Gemini
        result = gemini_client.generate_image(
            prompt=prompt,
            aspect_ratio="16:9"
        )

        if result and result.get('image_base64'):
            print(f"[API] Image generated successfully")
            return jsonify({
                'success': True,
                'image_base64': result['image_base64'],
                'section': section,
                'generated_at': datetime.now().isoformat()
            })
        else:
            return jsonify({
                'success': False,
                'error': 'Image generation failed'
            }), 500

    except Exception as e:
        print(f"[API ERROR] Image generation failed: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/generate-images', methods=['POST'])
def generate_images():
    """Generate images for newsletter sections using provided or auto-generated prompts (matches venue-voice)"""
    try:
        data = request.json
        sections = data.get('sections', {})
        prompts = data.get('prompts', {})  # Pre-generated or user-edited prompts

        print(f"\n[API] Generating images with Nano Banana (Gemini)...")
        print(f"[API] Received {len(prompts)} prompts")

        # Check if Gemini is available
        if not gemini_client or not gemini_client.is_available():
            return jsonify({
                'success': False,
                'error': 'Gemini API not configured. Please add GOOGLE_AI_API_KEY to your .env file. Get a key from https://aistudio.google.com/app/apikey'
            }), 503

        images = {}

        # Generate image for each prompt
        for section_name, prompt in prompts.items():
            safe_print(f"  [{section_name.upper()}] Prompt: {prompt[:80]}...")

            # Determine aspect ratio based on section
            # briteSpot/claims: larger images - use 16:9 landscape
            # spotlight/tips: can be 1:1 square
            if section_name in ['briteSpot', 'claims']:
                aspect_ratio = "16:9"  # Landscape for larger images
            else:
                aspect_ratio = "1:1"  # Square for other images

            # Generate with Gemini (Nano Banana)
            print(f"  [{section_name.upper()}] Calling Nano Banana...")
            image_result = gemini_client.generate_image(
                prompt=prompt,
                aspect_ratio=aspect_ratio
            )

            # Get the base64 image data
            image_data = image_result.get('image_base64', image_result.get('image_data', ''))

            # Resize image to exact newsletter dimensions
            if image_data:
                try:
                    from PIL import Image

                    # Decode base64 to PIL Image
                    image_bytes = base64.b64decode(image_data)
                    pil_image = Image.open(BytesIO(image_bytes))

                    # Determine target size based on section
                    if section_name in ['briteSpot', 'claims']:
                        # Larger images: 480px wide
                        target_width = 480
                        target_height = 260
                    else:
                        # Spotlight/Tips: 210px wide
                        target_width = 210
                        target_height = 250

                    print(f"  [{section_name.upper()}] Resizing from {pil_image.size} to {target_width}x{target_height}...")

                    # Calculate aspect ratios
                    img_aspect = pil_image.width / pil_image.height
                    target_aspect = target_width / target_height

                    # Resize maintaining aspect ratio, then crop to exact size
                    if img_aspect > target_aspect:
                        # Image is wider - resize based on height, then crop width
                        new_height = target_height
                        new_width = int(target_height * img_aspect)
                    else:
                        # Image is taller - resize based on width, then crop height
                        new_width = target_width
                        new_height = int(target_width / img_aspect)

                    # Resize maintaining aspect ratio
                    resized_temp = pil_image.resize((new_width, new_height), Image.Resampling.LANCZOS)

                    # Center crop to exact target dimensions
                    left = (new_width - target_width) // 2
                    top = (new_height - target_height) // 2
                    right = left + target_width
                    bottom = top + target_height

                    resized_image = resized_temp.crop((left, top, right, bottom))

                    # Convert back to base64
                    buffer = BytesIO()
                    resized_image.save(buffer, format='PNG', optimize=True)
                    resized_bytes = buffer.getvalue()
                    image_data = base64.b64encode(resized_bytes).decode('utf-8')

                    print(f"  [{section_name.upper()}] Resized successfully to {target_width}x{target_height}")

                except Exception as resize_error:
                    print(f"  [{section_name.upper()}] Resize failed, using original: {resize_error}")

            # Convert to data URL for frontend display
            image_url = f"data:image/png;base64,{image_data}" if image_data else ''

            images[section_name] = image_url
            print(f"  [{section_name.upper()}] SUCCESS - Image generated ({len(image_data) if image_data else 0} bytes)")

        print(f"[API] Generated {len(images)} images")

        return jsonify({
            'success': True,
            'images': images,
            'generated_at': datetime.now().isoformat()
        })

    except Exception as e:
        print(f"[API ERROR] {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


# ============================================================================
# ROUTES - HEADLINES & INTRO
# ============================================================================

@app.route('/api/generate-headlines', methods=['POST'])
def generate_headlines():
    """Generate newsletter headlines and subject line"""
    try:
        data = request.json
        content = data.get('content', {})
        month = data.get('month', 'january')

        print(f"\n[API] Generating headlines for {month}...")

        # Generate subject line
        subject_prompt = f"""Create an email subject line for the BriteCo Brief newsletter ({month.capitalize()} edition).

Newsletter highlights:
- Curious Claims section
- Insurance News Roundup
- InsurNews Spotlight
- Agent Advantage Tips

Requirements:
- 40-60 characters
- Engaging, professional
- No clickbait
- Reference the month or a key topic

Output ONLY the subject line, nothing else."""

        subject_result = claude_client.generate_content(
            prompt=subject_prompt,
            model="claude-opus-4-5-20251101",
            temperature=0.6,
            max_tokens=50
        )

        # Generate preview text
        preview_prompt = f"""Create email preview text (preheader) for the BriteCo Brief newsletter.

Requirements:
- 80-100 characters
- Complements the subject line
- Teases content inside

Output ONLY the preview text, nothing else."""

        preview_result = claude_client.generate_content(
            prompt=preview_prompt,
            model="claude-opus-4-5-20251101",
            temperature=0.5,
            max_tokens=60
        )

        print(f"[API] Headlines generated")

        return jsonify({
            'success': True,
            'subject_line': subject_result['content'].strip(),
            'preview_text': preview_result['content'].strip(),
            'generated_at': datetime.now().isoformat()
        })

    except Exception as e:
        print(f"[API ERROR] Headlines generation failed: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

# ============================================================================
# ROUTES - SUBJECT LINE OPTIONS
# ============================================================================

@app.route('/api/generate-subject-options', methods=['POST'])
def generate_subject_options():
    """Generate multiple subject line and preheader options with specified tone"""
    try:
        data = request.json
        content = data.get('content', {})
        tone = data.get('tone', 'professional')
        month = content.get('month', 'january')

        print(f"\n[API] Generating subject options for {month} with tone: {tone}...")

        # Define tone guidelines
        tone_guidelines = {
            'professional': 'Professional and informative, establishes credibility',
            'friendly': 'Warm, conversational, and approachable like talking to a colleague',
            'urgent': 'Creates urgency and encourages immediate action (without being alarmist)',
            'playful': 'Light-hearted and fun while maintaining professionalism',
            'exclusive': 'Makes the reader feel like they\'re getting insider access'
        }

        tone_desc = tone_guidelines.get(tone, tone_guidelines['professional'])

        # Generate subject lines
        subject_prompt = f"""Create 4 email subject line options for the BriteCo Brief newsletter ({month.capitalize()} edition).

Tone: {tone_desc}

Newsletter sections include:
- Curious Claims (unusual insurance claims stories)
- Insurance News Roundup (P&C industry news)
- InsurNews Spotlight (deep dive on trending topic)
- Agent Advantage Tips (actionable advice for agents)

Requirements:
- Each subject line should be 40-60 characters
- Make them engaging but not clickbait
- Reference the month or a key topic when appropriate
- Match the {tone} tone throughout

Output EXACTLY 4 subject lines, one per line, numbered 1-4. No other text."""

        subject_result = claude_client.generate_content(
            prompt=subject_prompt,
            model="claude-opus-4-5-20251101",
            temperature=0.7,
            max_tokens=300
        )

        # Parse subject lines
        subject_lines = []
        for line in subject_result['content'].strip().split('\n'):
            line = line.strip()
            if line:
                # Remove numbering like "1." or "1)" from start
                cleaned = re.sub(r'^[\d]+[\.\)]\s*', '', line)
                if cleaned:
                    subject_lines.append(cleaned)

        # Ensure we have at least 3 options
        if len(subject_lines) < 3:
            subject_lines = [
                f"{month.capitalize()} BriteCo Brief: Your P&C Industry Update",
                f"What Independent Agents Need to Know This {month.capitalize()}",
                f"BriteCo Brief: {month.capitalize()}'s Must-Read Insurance Insights",
                f"Your {month.capitalize()} Insurance Industry Roundup is Here"
            ]

        # Generate preheaders
        preheader_prompt = f"""Create 4 email preheader (preview text) options to complement subject lines for the BriteCo Brief newsletter.

Tone: {tone_desc}

Requirements:
- Each preheader should be 60-90 characters
- Tease content to encourage opening
- Complement subject lines without repeating them
- Match the {tone} tone

Output EXACTLY 4 preheader options, one per line, numbered 1-4. No other text."""

        preheader_result = claude_client.generate_content(
            prompt=preheader_prompt,
            model="claude-opus-4-5-20251101",
            temperature=0.7,
            max_tokens=400
        )

        # Parse preheaders
        preheaders = []
        for line in preheader_result['content'].strip().split('\n'):
            line = line.strip()
            if line:
                cleaned = re.sub(r'^[\d]+[\.\)]\s*', '', line)
                if cleaned:
                    preheaders.append(cleaned)

        # Ensure we have at least 3 options
        if len(preheaders) < 3:
            preheaders = [
                "Curious claims, industry trends, and tips to grow your book of business.",
                "From unusual claims to expert insights — your monthly P&C digest.",
                "Stay ahead with the latest news and strategies for independent agents.",
                "Industry updates, agent tips, and stories you won't want to miss."
            ]

        print(f"[API] Generated {len(subject_lines)} subject lines and {len(preheaders)} preheaders")

        return jsonify({
            'success': True,
            'subject_lines': subject_lines[:4],
            'preheaders': preheaders[:4],
            'tone': tone,
            'generated_at': datetime.now().isoformat()
        })

    except Exception as e:
        print(f"[API ERROR] Subject options generation failed: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


# ============================================================================
# ROUTES - BRAND CHECK
# ============================================================================

@app.route('/api/brand-check', methods=['POST'])
def brand_check():
    """Check newsletter content against brand guidelines - returns structured JSON suggestions"""
    try:
        data = request.json
        claims_content = data.get('claims_content', '')
        roundup_content = data.get('roundup_content', '')
        spotlight_content = data.get('spotlight_content', '')
        tips_content = data.get('tips_content', '')
        brite_spot_content = data.get('brite_spot_content', '')

        print(f"\n[API] Running brand check...")

        # Combine all content for checking
        full_content = f"""
BRITE SPOT SECTION:
{brite_spot_content}

CURIOUS CLAIMS SECTION:
{claims_content}

NEWS ROUNDUP SECTION:
{roundup_content}

INSURNEWS SPOTLIGHT SECTION:
{spotlight_content}

AGENT ADVANTAGE SECTION:
{tips_content}
"""

        check_prompt = f"""You are a brand consistency checker for BriteCo Brief, an insurance agent newsletter, using BriteCo's Editorial Style Guide.

BRAND GUIDELINES TO CHECK:

1. TONE & VOICE:
- Professional but approachable, knowledgeable, supportive
- Clear, concise, actionable
- Perspective: "We help independent insurance agents succeed"
- Avoid: Overly salesy language, jargon without explanation, competitor bashing

2. CONTENT FOCUS (P&C INSURANCE ONLY):
- INCLUDE: Property & casualty, homeowners, auto, commercial, workers comp, liability
- EXCLUDE: Health insurance, life insurance, Medicare/Medicaid, ACA content
- EXCLUDE: Political content, election news, international news
- US stories only (no international)

3. PUNCTUATION & FORMATTING:
- Use serial comma in lists
- Use em dash (—) with spaces around it
- Put punctuation inside quotation marks
- Use hyphen between two words modifying a noun

4. NUMBERS:
- Use % symbol (not "percent")
- Use numbers for ages (58-years-old, not fifty-eight)
- Spell out "zero" (not "0")

5. ABBREVIATIONS:
- No periods in country codes (US, UK not U.S., U.K.)
- Washington, DC (not D.C.)

6. BRITECO BRAND TERMINOLOGY:
- DO: Call BriteCo an "insurtech company" or "insurance provider"
- DO: Say "backed by an AM Best A+ rated Insurance Carrier"
- DO: Refer to website as brite.co or https://brite.co
- DON'T: Call BriteCo an "insurance company"
- DON'T: Say "we have AM Best policies" or "we are AM Best"
- DON'T: Refer to website as www.brite.co

Review the following newsletter content and identify SPECIFIC phrases that need to be changed.

Return a JSON object with an array of suggested changes:
{{
    "suggestions": [
        {{
            "section": "claims" | "roundup" | "spotlight" | "tips" | "brite_spot",
            "issue": "Brief description of the issue (e.g., 'Non-P&C content', 'Missing serial comma', 'Incorrect BriteCo terminology')",
            "original": "exact phrase from content that needs changing",
            "suggested": "what it should be changed to",
            "reason": "why this change is needed per brand guidelines"
        }}
    ]
}}

Only include items that actually need to be changed. If the content is perfect, return an empty suggestions array.

CONTENT TO REVIEW:
{full_content}"""

        check_result = claude_client.generate_content(
            prompt=check_prompt,
            model="claude-opus-4-5-20251101",
            temperature=0.2,
            max_tokens=1500
        )

        # Parse the JSON response
        check_text = check_result['content'].strip()

        # Remove markdown code blocks if present
        if check_text.startswith('```'):
            check_text = check_text.split('```')[1]
            if check_text.startswith('json'):
                check_text = check_text[4:]
            check_text = check_text.strip()

        try:
            check_results = json.loads(check_text)
        except json.JSONDecodeError as e:
            print(f"[API WARNING] Failed to parse brand check JSON: {e}")
            print(f"[API WARNING] Raw response: {check_text[:200]}")
            # Fallback if parsing fails
            check_results = {"suggestions": []}

        num_suggestions = len(check_results.get('suggestions', []))
        passed = num_suggestions == 0

        print(f"[API] Brand check complete - {num_suggestions} suggestions found")

        return jsonify({
            'success': True,
            'passed': passed,
            'check_results': check_results,
            'generated_at': datetime.now().isoformat()
        })

    except Exception as e:
        print(f"[API ERROR] Brand check failed: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500

# ============================================================================
# ROUTES - EXPORT & SHARING
# ============================================================================

@app.route('/api/send-preview', methods=['POST'])
def send_preview():
    """Send newsletter preview to team members via SendGrid"""
    try:
        data = request.json
        recipients = data.get('recipients', [])
        subject = data.get('subject', 'BriteCo Brief Preview')
        html_content = data.get('html', '')

        if not recipients or not html_content:
            return jsonify({"success": False, "error": "Recipients and HTML content required"}), 400

        safe_print(f"[API] Sending preview to {len(recipients)} recipients via SendGrid...")

        # Check SendGrid availability
        if not SENDGRID_AVAILABLE:
            return jsonify({
                "success": False,
                "error": "SendGrid library not installed. Run: pip install sendgrid"
            }), 500

        # Get SendGrid configuration (check both with and without underscore prefix for Secret Manager)
        sendgrid_api_key = os.environ.get('SENDGRID_API_KEY') or os.environ.get('_SENDGRID_API_KEY')
        from_email = os.environ.get('SENDGRID_FROM_EMAIL') or os.environ.get('_SENDGRID_FROM_EMAIL') or 'marketing@brite.co'
        from_name = os.environ.get('SENDGRID_FROM_NAME') or os.environ.get('_SENDGRID_FROM_NAME') or 'BriteCo Brief'

        safe_print(f"[API] SendGrid API key exists: {bool(sendgrid_api_key)}")
        safe_print(f"[API] Checking SENDGRID_API_KEY: {bool(os.environ.get('SENDGRID_API_KEY'))}, _SENDGRID_API_KEY: {bool(os.environ.get('_SENDGRID_API_KEY'))}")
        safe_print(f"[API] From email: {from_email}")

        if not sendgrid_api_key:
            return jsonify({
                "success": False,
                "error": "SendGrid API key not configured. Add SENDGRID_API_KEY environment variable."
            }), 500

        # Initialize SendGrid client
        sg = sendgrid.SendGridAPIClient(api_key=sendgrid_api_key)

        # Send email to each recipient
        sent_count = 0
        errors = []

        for recipient in recipients:
            try:
                safe_print(f"[API] Sending to: {recipient}")

                message = Mail(
                    from_email=(from_email, from_name),
                    to_emails=recipient,
                    subject=subject,
                    html_content=html_content
                )

                response = sg.send(message)

                safe_print(f"[API] SendGrid response status: {response.status_code}")

                if response.status_code in [200, 201, 202]:
                    sent_count += 1
                    safe_print(f"[API] Email sent successfully to: {recipient}")
                else:
                    error_msg = f"SendGrid returned status {response.status_code} for {recipient}"
                    safe_print(f"[API] {error_msg}")
                    errors.append(error_msg)

            except Exception as email_error:
                error_msg = f"Failed to send to {recipient}: {str(email_error)}"
                safe_print(f"[API] {error_msg}")
                # Log more details for debugging
                if hasattr(email_error, 'body'):
                    safe_print(f"[API] Error body: {email_error.body}")
                errors.append(error_msg)

        if sent_count == len(recipients):
            return jsonify({
                "success": True,
                "message": f"Preview sent to {sent_count} recipient(s)",
                "recipients": recipients,
                "from": from_email
            })
        elif sent_count > 0:
            return jsonify({
                "success": True,
                "message": f"Preview sent to {sent_count} of {len(recipients)} recipient(s)",
                "recipients": recipients[:sent_count],
                "errors": errors,
                "from": from_email
            })
        else:
            return jsonify({
                "success": False,
                "error": "Failed to send to any recipients",
                "details": errors
            }), 500

    except Exception as e:
        safe_print(f"[API] Send preview error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/export-to-docs', methods=['POST'])
def export_to_docs():
    """Export newsletter content to Google Docs and optionally send link via email"""
    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build

        data = request.json
        content = data.get('content', {})
        title = data.get('title', f"Agent Newsletter ({datetime.now().strftime('%B')}, {datetime.now().year})")
        month = data.get('month', datetime.now().strftime('%B'))
        year = data.get('year', datetime.now().year)
        send_email = data.get('send_email', False)
        recipients = data.get('recipients', [])  # List of email addresses

        # Google Drive folder ID for saving documents
        GOOGLE_DRIVE_FOLDER_ID = '1P4f_5lsvk-AKiSuZ9pks8LhcuUbvVP2m'

        safe_print(f"[API] Exporting to Google Docs: {title}")

        # Try both variable names for compatibility (with and without underscore prefix)
        creds_json = os.environ.get('GOOGLE_DOCS_CREDENTIALS') or os.environ.get('_GOOGLE_DOCS_CREDENTIALS')

        # Debug logging
        safe_print(f"[API] GOOGLE_DOCS_CREDENTIALS exists: {bool(os.environ.get('GOOGLE_DOCS_CREDENTIALS'))}")
        safe_print(f"[API] _GOOGLE_DOCS_CREDENTIALS exists: {bool(os.environ.get('_GOOGLE_DOCS_CREDENTIALS'))}")
        if creds_json:
            safe_print(f"[API] Credentials length: {len(creds_json)} chars, starts with: {creds_json[:50]}...")

        if not creds_json:
            return jsonify({
                "success": False,
                "error": "Google Docs credentials not configured. Set GOOGLE_DOCS_CREDENTIALS via Secret Manager."
            }), 500

        # Parse credentials
        try:
            creds_data = json.loads(creds_json)
            safe_print(f"[API] Parsed credentials, project_id: {creds_data.get('project_id', 'unknown')}")
            credentials = service_account.Credentials.from_service_account_info(
                creds_data,
                scopes=['https://www.googleapis.com/auth/documents', 'https://www.googleapis.com/auth/drive']
            )
        except json.JSONDecodeError as e:
            safe_print(f"[API] JSON parse error: {e}")
            safe_print(f"[API] Credentials value (first 100 chars): {creds_json[:100] if creds_json else 'None'}")
            return jsonify({
                "success": False,
                "error": f"Invalid JSON in credentials: {str(e)}"
            }), 500
        except Exception as e:
            safe_print(f"[API] Credentials error: {e}")
            return jsonify({
                "success": False,
                "error": f"Invalid Google credentials: {str(e)}"
            }), 500

        # Build the services
        docs_service = build('docs', 'v1', credentials=credentials)
        drive_service = build('drive', 'v3', credentials=credentials)

        # Create a new Google Doc directly in the shared folder using Drive API
        # This avoids the permission issue with docs.create()
        file_metadata = {
            'name': title,
            'mimeType': 'application/vnd.google-apps.document',
            'parents': [GOOGLE_DRIVE_FOLDER_ID]
        }

        created_file = drive_service.files().create(
            body=file_metadata,
            fields='id'
        ).execute()

        doc_id = created_file.get('id')
        doc_url = f"https://docs.google.com/document/d/{doc_id}/edit"

        safe_print(f"[API] Created Google Doc in folder: {doc_id}")

        # Build document content from newsletter sections
        requests_list = []

        # Helper to add text with formatting
        def add_text(text, bold=False, heading=False, index_offset=[1]):
            if not text:
                return
            text = text.strip() + '\n\n'
            start_index = index_offset[0]
            end_index = start_index + len(text)

            requests_list.append({
                'insertText': {
                    'location': {'index': start_index},
                    'text': text
                }
            })

            if heading:
                requests_list.append({
                    'updateParagraphStyle': {
                        'range': {'startIndex': start_index, 'endIndex': end_index - 1},
                        'paragraphStyle': {'namedStyleType': 'HEADING_2'},
                        'fields': 'namedStyleType'
                    }
                })
            elif bold:
                requests_list.append({
                    'updateTextStyle': {
                        'range': {'startIndex': start_index, 'endIndex': end_index - 1},
                        'textStyle': {'bold': True},
                        'fields': 'bold'
                    }
                })

            index_offset[0] = end_index

        # Add newsletter sections
        add_text(title, heading=True)

        if content.get('header_intro'):
            add_text(content['header_intro'])

        if content.get('introduction'):
            add_text('Introduction', bold=True)
            add_text(content['introduction'])

        if content.get('brite_spot'):
            add_text('The Brite Spot', bold=True)
            add_text(content['brite_spot'])

        if content.get('curious_claims'):
            add_text('Curious Claims', bold=True)
            add_text(content['curious_claims'])

        if content.get('roundup'):
            add_text('Insurance News Roundup', bold=True)
            roundup_text = ''
            if isinstance(content['roundup'], list):
                for item in content['roundup']:
                    bullet = item.get('summary', item) if isinstance(item, dict) else item
                    roundup_text += f"• {bullet}\n"
            else:
                roundup_text = content['roundup']
            add_text(roundup_text)

        if content.get('spotlight'):
            add_text('InsurNews Spotlight', bold=True)
            spotlight = content['spotlight']
            if isinstance(spotlight, dict):
                if spotlight.get('subheader'):
                    add_text(spotlight['subheader'])
                if spotlight.get('body'):
                    add_text(spotlight['body'])
            else:
                add_text(str(spotlight))

        if content.get('agent_tips'):
            add_text('Agent Advantage', bold=True)
            tips = content['agent_tips']
            if isinstance(tips, dict) and tips.get('intro'):
                add_text(tips['intro'])
                for i, tip in enumerate(tips.get('tips', []), 1):
                    tip_text = tip.get('tip', tip) if isinstance(tip, dict) else tip
                    add_text(f"{i}. {tip_text}")
            elif isinstance(tips, list):
                for i, tip in enumerate(tips, 1):
                    tip_text = tip.get('tip', tip) if isinstance(tip, dict) else tip
                    add_text(f"{i}. {tip_text}")
            else:
                add_text(str(tips))

        # Execute batch update
        if requests_list:
            docs_service.documents().batchUpdate(
                documentId=doc_id,
                body={'requests': requests_list}
            ).execute()
            safe_print(f"[API] Document content updated")

        # Make the document accessible via link (anyone with link can view)
        drive_service.permissions().create(
            fileId=doc_id,
            body={'type': 'anyone', 'role': 'reader'}
        ).execute()
        safe_print(f"[API] Document sharing enabled")

        # Optionally send email with the link to multiple recipients via SendGrid
        emails_sent = []
        email_errors = []
        if send_email and recipients:
            try:
                # Check both with and without underscore prefix for Secret Manager
                sendgrid_api_key = os.environ.get('SENDGRID_API_KEY') or os.environ.get('_SENDGRID_API_KEY')
                from_email = os.environ.get('SENDGRID_FROM_EMAIL') or os.environ.get('_SENDGRID_FROM_EMAIL') or 'marketing@brite.co'
                from_name = os.environ.get('SENDGRID_FROM_NAME') or os.environ.get('_SENDGRID_FROM_NAME') or 'BriteCo Brief'

                if sendgrid_api_key and SENDGRID_AVAILABLE:
                    sg = sendgrid.SendGridAPIClient(api_key=sendgrid_api_key)

                    for recipient in recipients:
                        try:
                            email_html = f"""
                            <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
                                <h2 style="color: #008181;">Agent Newsletter Ready for Review</h2>
                                <p>Hello,</p>
                                <p>The <strong>{month} {year}</strong> Agent Newsletter has been exported to Google Docs and is ready for your review.</p>
                                <p style="margin: 20px 0;">
                                    <a href="{doc_url}" style="background: #008181; color: white; padding: 12px 24px; text-decoration: none; border-radius: 4px; display: inline-block;">
                                        Open Google Doc
                                    </a>
                                </p>
                                <p style="color: #666; font-size: 14px;">Or copy this link: {doc_url}</p>
                                <hr style="border: none; border-top: 1px solid #eee; margin: 20px 0;">
                                <p style="color: #999; font-size: 12px;">Sent by BriteCo Brief Newsletter Generator</p>
                            </div>
                            """

                            message = Mail(
                                from_email=(from_email, from_name),
                                to_emails=recipient,
                                subject=f"Agent Newsletter ({month}, {year}) - Ready for Review",
                                html_content=email_html
                            )

                            response = sg.send(message)

                            if response.status_code in [200, 201, 202]:
                                emails_sent.append(recipient)
                                safe_print(f"[API] Email sent to {recipient}")
                            else:
                                error_msg = f"SendGrid returned status {response.status_code} for {recipient}"
                                email_errors.append(error_msg)
                                safe_print(f"[API] {error_msg}")

                        except Exception as email_error:
                            error_msg = f"Failed to send to {recipient}: {str(email_error)}"
                            email_errors.append(error_msg)
                            safe_print(f"[API] {error_msg}")
                else:
                    safe_print("[API] SendGrid not configured (SENDGRID_API_KEY not set)")
                    email_errors.append("SendGrid not configured")
            except Exception as e:
                safe_print(f"[API] Email send failed: {e}")
                # Don't fail the whole operation if email fails

        return jsonify({
            "success": True,
            "doc_url": doc_url,
            "doc_id": doc_id,
            "title": title,
            "emails_sent": emails_sent,
            "email_errors": email_errors,
            "message": f"Newsletter exported to Google Docs{f' and {len(emails_sent)} email(s) sent' if emails_sent else ''}"
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        safe_print(f"[API] Export error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/send-doc-email', methods=['POST'])
def send_doc_email():
    """Send email with Google Doc link (separate from export)"""
    try:
        data = request.json
        doc_url = data.get('doc_url', '')
        month = data.get('month', '')
        year = data.get('year', datetime.now().year)
        recipients = data.get('recipients', [])

        if not doc_url:
            return jsonify({"success": False, "error": "No document URL provided"}), 400

        if not recipients:
            return jsonify({"success": False, "error": "No recipients provided"}), 400

        safe_print(f"[API] Sending doc email to {len(recipients)} recipients")

        if not SENDGRID_AVAILABLE:
            return jsonify({"success": False, "error": "SendGrid not available"}), 500

        # Check both with and without underscore prefix for Secret Manager
        sendgrid_api_key = os.environ.get('SENDGRID_API_KEY') or os.environ.get('_SENDGRID_API_KEY')
        from_email = os.environ.get('SENDGRID_FROM_EMAIL') or os.environ.get('_SENDGRID_FROM_EMAIL') or 'marketing@brite.co'
        from_name = os.environ.get('SENDGRID_FROM_NAME') or os.environ.get('_SENDGRID_FROM_NAME') or 'BriteCo Brief'

        if not sendgrid_api_key:
            return jsonify({"success": False, "error": "SendGrid API key not configured"}), 500

        sg = sendgrid.SendGridAPIClient(api_key=sendgrid_api_key)

        emails_sent = []
        email_errors = []

        for recipient in recipients:
            try:
                email_html = f"""
                <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
                    <h2 style="color: #008181;">Agent Newsletter Ready for Review</h2>
                    <p>Hello,</p>
                    <p>The <strong>{month} {year}</strong> Agent Newsletter has been exported to Google Docs and is ready for your review.</p>
                    <p style="margin: 20px 0;">
                        <a href="{doc_url}" style="background: #008181; color: white; padding: 12px 24px; text-decoration: none; border-radius: 4px; display: inline-block;">
                            Open Google Doc
                        </a>
                    </p>
                    <p style="color: #666; font-size: 14px;">Or copy this link: {doc_url}</p>
                    <hr style="border: none; border-top: 1px solid #eee; margin: 20px 0;">
                    <p style="color: #999; font-size: 12px;">Sent by BriteCo Brief Newsletter Generator</p>
                </div>
                """

                message = Mail(
                    from_email=Email(from_email, from_name),
                    to_emails=To(recipient),
                    subject=f"Agent Newsletter ({month} {year}) - Ready for Review",
                    html_content=HtmlContent(email_html)
                )

                response = sg.send(message)
                safe_print(f"[API] Email sent to {recipient}, status: {response.status_code}")
                emails_sent.append(recipient)
            except Exception as email_error:
                safe_print(f"[API] Failed to send to {recipient}: {email_error}")
                email_errors.append(str(email_error))

        if emails_sent:
            return jsonify({
                "success": True,
                "emails_sent": emails_sent,
                "errors": email_errors
            })
        else:
            return jsonify({
                "success": False,
                "error": email_errors[0] if email_errors else "Failed to send emails"
            }), 500

    except Exception as e:
        import traceback
        traceback.print_exc()
        safe_print(f"[API] Send doc email error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


# ============================================================================
# ROUTES - ONTRAPORT
# ============================================================================

@app.route('/api/send-to-ontraport', methods=['POST'])
def send_to_ontraport():
    """Send newsletter to Ontraport for distribution"""
    try:
        data = request.json
        html_content = data.get('html', '')
        subject = data.get('subject', 'BriteCo Brief')

        if not html_content:
            return jsonify({"success": False, "error": "HTML content required"}), 400

        if not ontraport_client:
            return jsonify({"success": False, "error": "Ontraport client not available"}), 500

        safe_print(f"[API] Sending to Ontraport...")

        # Convert to plain text for Ontraport
        plain_text = html_to_plain_text(html_content)

        # Send to Ontraport objects (10004 and 10007)
        result = ontraport_client.create_email(
            subject=subject,
            html_content=html_content,
            plain_text=plain_text,
            from_email=ONTRAPORT_CONFIG['from_email'],
            from_name=ONTRAPORT_CONFIG['from_name'],
            object_ids=ONTRAPORT_CONFIG['objects']
        )

        if result.get('success'):
            return jsonify({
                "success": True,
                "message": "Newsletter sent to Ontraport",
                "email_id": result.get('email_id')
            })
        else:
            return jsonify({
                "success": False,
                "error": result.get('error', 'Ontraport send failed')
            }), 500

    except Exception as e:
        safe_print(f"[API] Ontraport error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

# ============================================================================
# MAIN
# ============================================================================

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    print(f"\n=== BriteCo Brief API Server ===")
    print(f"Starting on port {port}")
    app.run(host='0.0.0.0', port=port, debug=True)
