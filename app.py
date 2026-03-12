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
import secrets
from io import BytesIO
from datetime import datetime
from functools import wraps
from flask import Flask, request, jsonify, send_from_directory, Response, redirect, session, url_for
from flask_cors import CORS
from authlib.integrations.flask_client import OAuth
from dotenv import load_dotenv
from werkzeug.middleware.proxy_fix import ProxyFix
from bs4 import BeautifulSoup
import pytz

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
    get_style_guide_for_prompt, get_search_sources_prompt,
    get_humanization_guidelines, get_full_style_guide_for_section
)
from config.model_config import get_model_for_task

# Chicago timezone for timestamps
CHICAGO_TZ = pytz.timezone('America/Chicago')

app = Flask(__name__, static_folder='.')
CORS(app)

# Fix for running behind Cloud Run's proxy - ensures correct HTTPS URLs
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

# Session configuration
app.secret_key = os.environ.get('FLASK_SECRET_KEY', secrets.token_hex(32))

# OAuth configuration
oauth = OAuth(app)
google = oauth.register(
    name='google',
    client_id=os.environ.get('GOOGLE_CLIENT_ID'),
    client_secret=os.environ.get('GOOGLE_CLIENT_SECRET'),
    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
    client_kwargs={'scope': 'openid email profile'}
)

# Allowed email domain
ALLOWED_DOMAIN = 'brite.co'

def login_required(f):
    """Decorator to require authentication"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user' not in session:
            return redirect('/auth/login')
        return f(*args, **kwargs)
    return decorated_function

def get_current_user():
    """Get current user from session"""
    return session.get('user')

# Auth-exempt paths (no login required)
AUTH_EXEMPT_PATHS = {'/health', '/auth/login', '/auth/callback', '/auth/logout', '/api/user'}

@app.before_request
def require_auth():
    """Enforce authentication on all /api/* routes except exempted paths"""
    if request.path in AUTH_EXEMPT_PATHS:
        return None
    if request.path.startswith('/api/'):
        if 'user' not in session:
            return jsonify({'error': 'Authentication required'}), 401
    return None

def validate_gcs_filename(filename, allowed_prefixes):
    """Validate GCS blob filename to prevent path traversal and unauthorized access"""
    if not filename:
        return False
    if '..' in filename:
        return False
    return any(filename.startswith(prefix) for prefix in allowed_prefixes)


def validate_url(url):
    """Validate a URL to prevent SSRF attacks. Returns (is_valid, error_message)."""
    from urllib.parse import urlparse
    import ipaddress
    import socket

    if not url:
        return False, 'URL is required'

    parsed = urlparse(url)

    # Only allow http and https schemes
    if parsed.scheme not in ('http', 'https'):
        return False, f'Invalid URL scheme: {parsed.scheme}. Only http and https are allowed.'

    hostname = parsed.hostname
    if not hostname:
        return False, 'Invalid URL: no hostname'

    # Resolve hostname to IP and check for private/reserved ranges
    try:
        resolved_ips = socket.getaddrinfo(hostname, None)
        for family, type_, proto, canonname, sockaddr in resolved_ips:
            ip = ipaddress.ip_address(sockaddr[0])
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                return False, 'URLs pointing to private/internal networks are not allowed'
    except (socket.gaierror, ValueError):
        return False, f'Cannot resolve hostname: {hostname}'

    return True, None


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

# Initialize GCS for drafts
GCS_BUCKET_NAME = 'briteco-brief-drafts'
GCS_IMAGES_BUCKET = 'briteco-brief-images'
gcs_client = None
try:
    from google.cloud import storage as gcs_storage
    gcs_client = gcs_storage.Client()
    print("[OK] GCS initialized")
except Exception as e:
    print(f"[WARNING] GCS not available: {e}")

# ============================================================================
# ROUTES - STATIC FILES
# ============================================================================

@app.route('/')
def serve_demo():
    """Serve the main app - redirect to login if not authenticated"""
    user = get_current_user()
    if not user:
        return redirect('/auth/login')

    with open('index.html', 'r', encoding='utf-8') as f:
        html = f.read()

    # Inject user info for the frontend
    user_script = f'''<script>
    window.AUTH_USER = {json.dumps(user)};
    </script>
</head>'''
    html = html.replace('</head>', user_script, 1)  # Only replace first occurrence

    return Response(html, mimetype='text/html')

@app.route('/auth/login')
def auth_login():
    """Initiate Google OAuth login"""
    if get_current_user():
        return redirect('/')
    redirect_uri = url_for('auth_callback', _external=True)
    return google.authorize_redirect(redirect_uri)

@app.route('/auth/callback')
def auth_callback():
    """Handle Google OAuth callback"""
    try:
        token = google.authorize_access_token()
        user_info = token.get('userinfo')
        if not user_info:
            return 'Failed to get user info', 400
        email = user_info.get('email', '')
        if not email.endswith(f'@{ALLOWED_DOMAIN}'):
            return f'''
            <html>
            <head><title>Access Denied</title></head>
            <body style="font-family: system-ui; display: flex; justify-content: center; align-items: center; height: 100vh; margin: 0; background: #1a1a2e; color: white;">
                <div style="text-align: center; padding: 40px;">
                    <h1>Access Denied</h1>
                    <p>Only @{ALLOWED_DOMAIN} email addresses are allowed.</p>
                    <p style="color: #718096;">You signed in with: {email}</p>
                    <a href="/auth/logout" style="color: #31D7CA;">Try a different account</a>
                </div>
            </body>
            </html>
            ''', 403
        session['user'] = {
            'email': email,
            'name': user_info.get('name', ''),
            'picture': user_info.get('picture', '')
        }
        return redirect('/')
    except Exception as e:
        print(f"Auth callback error: {e}")
        return f'Authentication failed: {str(e)}', 400

@app.route('/auth/logout')
def auth_logout():
    """Log out the user"""
    session.pop('user', None)
    return redirect('/auth/login')

@app.route('/api/user')
def get_user():
    """Get current user info"""
    user = get_current_user()
    if user:
        return jsonify(user)
    return jsonify(None), 401

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


def analyze_industry_impact(results: list, theme_context: dict = None) -> list:
    """
    Use LLM to analyze each result for insurance industry impact.
    Generates newsletter-ready headlines and impact scores.
    If theme_context is provided, results are scored with editorial angle awareness.
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

        # Add theme awareness if active
        theme_instruction = ""
        if theme_context:
            theme_headline = theme_context.get('headline', '')
            theme_desc = theme_context.get('description', '')
            theme_instruction = f"""
EDITORIAL THEME: The editor is building a feature story around this angle:
- "{theme_headline}"
- Angle: "{theme_desc}"
Prioritize articles that directly support THIS ANGLE. Score them higher on impact.
Articles only tangentially related to the theme keywords (but not the angle) should be scored lower.
"""

        prompt = f"""You are analyzing news articles for an insurance agent newsletter.

For each article, determine its impact on P&C insurance agents and their clients.
{theme_instruction}
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


def analyze_story_angles(results: list, user_query: str, theme_context: dict = None) -> list:
    """
    Use LLM to analyze articles and surface interesting story angles for newsletters.
    If theme_context is provided, angles are weighted toward the editorial theme.
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

        # Add theme awareness if active
        theme_instruction = ""
        if theme_context:
            theme_headline = theme_context.get('headline', '')
            theme_desc = theme_context.get('description', '')
            theme_instruction = f"""
EDITORIAL THEME: The editor is building a feature story around this angle:
- "{theme_headline}"
- Angle: "{theme_desc}"
Frame your story angles to connect each article back to this editorial theme where relevant.
Articles that don't naturally connect to the theme should still get useful angles, but prioritize theme-aligned framing.
"""

        prompt = f"""You are a newsletter editor for insurance agents. The user searched for: "{user_query}"
{theme_instruction}
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


def enrich_results_with_llm(results: list, original_query: str, theme_context: dict = None) -> list:
    """
    Use LLM to generate newsletter-ready content from research results.
    Produces three-section format: headline, industry_data, so_what
    Model selection is driven by config/vision_models.yaml task_assignments.
    If theme_context is provided, results are scored for relevance to the editorial angle.
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

        # Build theme-aware prompt if editorial theme is active
        theme_instruction = ""
        if theme_context:
            theme_headline = theme_context.get('headline', '')
            theme_desc = theme_context.get('description', '')
            theme_instruction = f"""
EDITORIAL THEME CONTEXT:
The editor is researching a specific feature story angle:
- Theme: "{theme_headline}"
- Angle: "{theme_desc}"

When scoring impact, BOOST results that directly support this editorial angle.
Results that are tangential to the theme (related topic but different angle) should be scored LOWER.
For example, if the theme is about "AI risk in agencies", an article about general compliance updates
should be MEDIUM even if compliance is mentioned in the theme headline — the ANGLE matters more than keywords.
"""

        prompt = f"""You are analyzing research findings for an insurance agent newsletter. The user searched for: "{original_query}"
{theme_instruction}
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
        time_window = data.get('time_window', '30d')
        exclude_urls = data.get('exclude_urls', [])
        theme_context = data.get('theme_context', None)  # Optional: {headline, description} from theme discovery

        safe_print(f"\n[API v2] Perplexity Research: query='{query}', time_window={time_window}, themed={bool(theme_context)}")

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
            results = enrich_results_with_llm(results, query, theme_context=theme_context)

        # Build query description for UI
        time_desc = {
            '7d': 'past week',
            '30d': 'past month'
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
        theme_context = data.get('theme_context', None)  # Optional: {headline, description} from theme discovery

        safe_print(f"\n[API v2] Insight Builder: Searching ALL 8 signals, themed={bool(theme_context)}")

        # Step 1: Search all 8 signals simultaneously
        raw_results = search_all_signals(time_window=time_window, exclude_urls=exclude_urls)

        # Step 2: Analyze results with GPT for industry impact
        enriched_results = analyze_industry_impact(raw_results, theme_context=theme_context)

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
        theme_context = data.get('theme_context', None)  # Optional: {headline, description} from theme discovery

        safe_print(f"\n[API v2] Source Explorer: query='{query}', packs={source_packs}, time_window={time_window}, themed={bool(theme_context)}")

        # Convert time window to human-readable for query
        time_desc = {
            '7d': 'past week',
            '30d': 'past month'
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
        results = analyze_story_angles(results, query, theme_context=theme_context)

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
        reference_text = data.get('reference_text', '')

        if not content and not reference_text:
            return jsonify({'success': False, 'error': 'Content or reference required'}), 400

        print(f"\n[API] Rewriting Brite Spot content ({tone} tone)...")

        if not claude_client:
            return jsonify({'success': False, 'error': 'Claude client not available'}), 500

        tone_instructions = {
            'witty': 'Use a clever, witty tone with subtle humor — smart wordplay welcome but keep it tasteful and professional',
            'friendly': 'Use a warm, conversational, and approachable tone',
            'exciting': 'Make it energetic and exciting with action words',
            'informative': 'Keep it clear, factual, and professional',
            'professional': 'Use formal business language and tone'
        }

        rewrite_bs_system = """You rewrite BriteCo company updates for the agent newsletter "The Brite Spot" section.

EXAMPLES FROM PAST ISSUES (match this warm, specific voice):
- "We are happy to announce the winners of our yearly independent agent survey. Three agents won $200 gift cards just for completing the form."
- "BriteCo will be at three insurance industry trade shows this month -- we'd love to see you and say hello!"
- "As 2025 winds down, we wanted to wish you and yours a very happy holiday season and thank you for another great year of partnership."

VOICE:
- Sound warm and genuine -- like writing to a colleague
- Use contractions naturally (we're, you'll, don't)
- Include specific details (names, numbers, dates) when available
- AVOID: "leverage", "robust", "comprehensive", "cutting-edge", "innovative"
"""

        rewrite_bs_prompt = f"""Rewrite this content for "The Brite Spot" section.

ORIGINAL CONTENT:
{content or '(none — write from the reference material below)'}
{f'''
REFERENCE ARTICLES / NOTES (use for context, facts, and story angle):
{reference_text}
''' if reference_text else ''}
REQUIREMENTS:
- Maximum 100 words
- {tone_instructions.get(tone, 'Professional but approachable')}
- Focus on value to independent insurance agents
- Include a subtle call to action

Output ONLY the rewritten content, no labels or explanations."""

        result = claude_client.generate_content(
            prompt=rewrite_bs_prompt,
            system_prompt=rewrite_bs_system,
            model="claude-opus-4-5-20251101",
            temperature=0.6,
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


@app.route('/api/rewrite-section', methods=['POST'])
def rewrite_section():
    """Rewrite newsletter section content using Claude with style guide"""
    try:
        data = request.json
        content = data.get('content', '')
        section = data.get('section', '')
        month = data.get('month', 'january')
        tone = data.get('tone', '')

        if not content:
            return jsonify({'success': False, 'error': 'Content required'}), 400

        if not section:
            return jsonify({'success': False, 'error': 'Section type required'}), 400

        print(f"\n[API] Rewriting {section} content (tone: {tone})...")

        tone_instructions = {
            'witty': 'Use a clever, witty tone with subtle humor — smart wordplay welcome but keep it tasteful and professional.',
            'friendly': 'Use a warm, conversational, and approachable tone.',
            'exciting': 'Make it energetic and exciting with action words.',
            'informative': 'Keep it clear, factual, and professional.',
            'professional': 'Use formal business language and tone.'
        }
        tone_line = f"\n- TONE: {tone_instructions.get(tone, '')}" if tone else ""

        if not claude_client:
            return jsonify({'success': False, 'error': 'Claude client not available'}), 500

        # Shared system prompt for all section rewrites
        rewrite_system = """You are a professional newsletter copywriter for BriteCo Brief, a monthly newsletter for independent P&C insurance agents.

EXAMPLES FROM PAST ISSUES (match this voice exactly):
- "Thank you to everyone who completed our annual independent agent survey and vied for the chance to win a $200 gift card. We have now picked our winners. Keep reading to find out if you are a recipient and get the latest on the homeowners insurance crisis that's still wreaking havoc on the industry."
- "It's hard to believe it's been 20 years since Hurricane Katrina caused one of the biggest catastrophes in US history and had an astronomical impact on insurance."
- "From all of us at BriteCo, we are wishing you a very happy holiday season! As you make your list and check it twice, we wanted to remind you of one important item to not forget: filling out our brief Independent Agent Survey."
- "A new J.D. Power study has found that 47% of homeowners saw premium increases in the past year, the highest jump in over a decade. You can protect your clients from a jewelry claim that sparks a higher homeowners premium or non-renewal by switching them from an HO rider/floater to a BriteCo stand-alone policy."
- "As the homeowners crisis continues to loom, and agencies and consumers are faced with skyrocketing premiums and the risk of non-renewals, we want to know how this directly affects you and your clients."

VOICE:
- Use contractions naturally (it's, we're, you'll)
- Be warm and collegial, not stiff
- Sound like a real person writing to colleagues
- Include specific details (names, numbers, percentages) when available
- AVOID: "leverage", "robust", "comprehensive", "cutting-edge", "innovative", "in today's ever-evolving landscape", "excited to announce"

KEY MESSAGING (use when relevant):
- No claims reporting to CLUE or A-Plus (doesn't impact HO premium)
- Premium savings of 20-40% over HO riders/floaters
- AM Best A+ rated carrier
- 12% recurring commissions
- 4,500+ agents already appointed"""

        # Section-specific user prompts
        section_prompts = {
            'header_intro': f"""Rewrite this newsletter header intro for the {month.capitalize()} edition.

ORIGINAL CONTENT:
{content}

REQUIREMENTS:
- Length: 2-4 sentences (50-80 words)
- Warm but professional greeting
- Reference the current month or tease key topics
- Start with something specific, not generic{tone_line}

Output ONLY the rewritten content, no labels or explanations.""",

            'brite_spot_intro': f"""Rewrite this intro paragraph for "The Brite Spot" section.

ORIGINAL CONTENT:
{content}

REQUIREMENTS:
- Length: 2-4 sentences
- Warm, supportive, promotional (but not pushy)
- Highlight agent benefits (commissions, ease of use, client value)
- Lead with the benefit or a specific fact/stat{tone_line}

Output ONLY the rewritten content, no labels or explanations.""",

            'brite_spot_bullets': f"""Rewrite these bullet points for "The Brite Spot" section.

ORIGINAL CONTENT:
{content}

REQUIREMENTS:
- Keep as bullet points (one per line, starting with bullet)
- Each bullet: 1-2 concise sentences
- Focus on value to independent insurance agents
- Action-oriented when possible
- Total: 3-5 bullets{tone_line}

Output ONLY the rewritten bullets, no labels or explanations.""",

            'special_section': f"""Rewrite this special section content.

{content}

REQUIREMENTS:
- Keep it concise: 2-3 short paragraphs, under 100 words total
- Professional, warm, and engaging{tone_line}
- Focus on value to independent insurance agents
- No markdown formatting — output plain text only

Output ONLY the content, no labels or explanations."""
        }

        prompt = section_prompts.get(section)
        if not prompt:
            return jsonify({'success': False, 'error': f'Unknown section type: {section}'}), 400

        result = claude_client.generate_content(
            prompt=prompt,
            system_prompt=rewrite_system,
            model="claude-opus-4-5-20251101",
            temperature=0.6,
            max_tokens=400
        )

        return jsonify({
            'success': True,
            'rewritten': result['content'].strip(),
            'original': content,
            'section': section
        })

    except Exception as e:
        print(f"[API ERROR] Section rewrite: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


# ============================================================================
# ROUTES - FEATURE SPOTLIGHT (Multi-Source)
# ============================================================================


@app.route('/api/discover-spotlight-themes', methods=['POST'])
def discover_spotlight_themes():
    """Layer 1: Auto-discover feature themes via broad Perplexity search + GPT clustering"""
    try:
        data = request.json
        month = data.get('month', '')
        time_window = data.get('time_window', '30d')

        safe_print(f"\n[API] Discovering spotlight themes for month={month}, time_window={time_window}")

        # Step 1: Run a broad Perplexity discovery search
        discovery_query = (
            f"P&C insurance industry major trends breaking news investigative topics {month} {datetime.now().year} "
            "homeowners rate changes catastrophe losses auto insurance trends "
            "commercial insurance market regulatory changes InsurTech innovation "
            "claims trends reinsurance market climate risk independent agent challenges "
            "consumer behavior market shifts supply chain disruption"
        )

        discovery_results = []
        if perplexity_client and perplexity_client.is_available():
            discovery_results = perplexity_client.search(
                query=discovery_query,
                time_window=time_window,
                max_results=12
            )
            safe_print(f"[API] Discovery search returned {len(discovery_results)} results")

        if not discovery_results:
            return jsonify({
                'success': False,
                'error': 'No results from discovery search. Try again or search manually.',
                'themes': []
            })

        # Step 2: Send results to GPT for theme clustering
        results_text = ""
        for i, r in enumerate(discovery_results):
            results_text += f"\nArticle {i+1}:\n- Title: {r.get('title', '')}\n- URL: {r.get('url', '')}\n- Summary: {r.get('snippet', r.get('summary', ''))[:300]}\n"

        model_config = get_model_for_task('research_enrichment')
        model_id = model_config.get('id', 'gpt-5.2')
        max_tokens_param = model_config.get('max_tokens_param', 'max_tokens')

        cluster_prompt = f"""You are an editorial assistant for "The BriteCo Brief", a monthly P&C insurance newsletter for independent agents.

Analyze these {len(discovery_results)} recent articles and identify 3-4 distinct FEATURE STORY themes. Each theme should be a compelling, in-depth topic for a feature spotlight article.

{results_text}

For each theme, return:
1. "headline" - A compelling editorial headline (not just a topic label)
2. "description" - One sentence explaining the SPECIFIC ANGLE and why agents should care
3. "search_query" - A search query focused on the UNIQUE ANGLE of this theme (see rules below)
4. "source_urls" - Array of URLs from the articles above that support this theme

CRITICAL rules for "search_query":
- The search_query must target the SPECIFIC ANGLE, not repeat all keywords from the headline
- BAD: "compliance distribution tech AI agency operations insurance" (keyword dump)
- GOOD: "AI risk insurance agency E&O liability automation compliance gaps" (angle-focused)
- If the headline is "X and Y Are Changing Z — Where A Helps and B Hurts", the search_query should focus on the A/B angle, NOT on X and Y
- Keep it to 6-10 words maximum, focused on what makes this angle UNIQUE

Return ONLY a JSON array:
[
  {{
    "headline": "...",
    "description": "...",
    "search_query": "...",
    "source_urls": ["...", "..."]
  }}
]

Guidelines:
- Themes should be DISTINCT (not overlapping)
- Prioritize themes with direct impact on independent P&C agents and their clients
- Prefer data-driven stories (rate changes, market shifts, loss trends)
- Avoid generic topics — each theme should have a specific angle"""

        api_params = {
            "model": model_id,
            "messages": [{"role": "user", "content": cluster_prompt}],
            "temperature": 0.3,
        }
        api_params[max_tokens_param] = 1500

        response = openai_client.client.chat.completions.create(**api_params)
        content = response.choices[0].message.content.strip()

        # Parse JSON
        if content.startswith("```"):
            content = re.sub(r"^```[a-zA-Z]*\n", "", content)
            content = re.sub(r"\n```$", "", content).strip()

        themes = json.loads(content)
        safe_print(f"[API] Discovered {len(themes)} spotlight themes")

        return jsonify({
            'success': True,
            'themes': themes,
            'discovery_results_count': len(discovery_results),
            'generated_at': datetime.now().isoformat()
        })

    except Exception as e:
        safe_print(f"[API ERROR] Discover spotlight themes: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e), 'themes': []}), 500


@app.route('/api/refine-spotlight-themes', methods=['POST'])
def refine_spotlight_themes():
    """Layer 2: Re-cluster themes from user's aggregated search results"""
    try:
        data = request.json
        articles = data.get('articles', [])
        current_theme = data.get('current_theme', '')

        if len(articles) < 3:
            return jsonify({
                'success': False,
                'error': 'Need at least 3 articles to refine themes.',
                'themes': []
            })

        safe_print(f"\n[API] Refining spotlight themes from {len(articles)} articles (current: {current_theme})")

        # Build article summaries for GPT
        results_text = ""
        seen_urls = set()
        for i, a in enumerate(articles):
            url = a.get('url', '')
            if url in seen_urls:
                continue
            seen_urls.add(url)
            results_text += f"\nArticle {i+1}:\n- Title: {a.get('title', a.get('headline', ''))}\n- URL: {url}\n- Summary: {a.get('snippet', a.get('summary', a.get('so_what', '')))[:300]}\n"

        model_config = get_model_for_task('research_enrichment')
        model_id = model_config.get('id', 'gpt-5.2')
        max_tokens_param = model_config.get('max_tokens_param', 'max_tokens')

        refine_prompt = f"""You are an editorial assistant for "The BriteCo Brief", a P&C insurance newsletter for independent agents.

The editor has been researching articles{f' around the theme: "{current_theme}"' if current_theme else ''}. Analyze their collected articles and suggest 3-4 REFINED feature story angles.

{results_text}

These refined themes should be MORE SPECIFIC than broad topic areas — think investigative angles, surprising data points, or actionable narratives.

Return ONLY a JSON array:
[
  {{
    "headline": "A specific, compelling editorial headline",
    "description": "One sentence on the angle and agent relevance",
    "search_query": "A focused follow-up search query for this angle",
    "source_urls": ["urls", "from", "above"]
  }}
]

Guidelines:
- Be MORE SPECIFIC than the initial themes — narrow the angle
- Each theme should have enough source material (2+ articles) to write a full feature
- Prioritize stories with clear implications for independent agents
- Include data-driven angles where possible"""

        api_params = {
            "model": model_id,
            "messages": [{"role": "user", "content": refine_prompt}],
            "temperature": 0.3,
        }
        api_params[max_tokens_param] = 1500

        response = openai_client.client.chat.completions.create(**api_params)
        content = response.choices[0].message.content.strip()

        if content.startswith("```"):
            content = re.sub(r"^```[a-zA-Z]*\n", "", content)
            content = re.sub(r"\n```$", "", content).strip()

        themes = json.loads(content)
        safe_print(f"[API] Refined into {len(themes)} spotlight themes")

        return jsonify({
            'success': True,
            'themes': themes,
            'articles_analyzed': len(seen_urls),
            'generated_at': datetime.now().isoformat()
        })

    except Exception as e:
        safe_print(f"[API ERROR] Refine spotlight themes: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e), 'themes': []}), 500


@app.route('/api/search-spotlight-articles', methods=['POST'])
def search_spotlight_articles():
    """Search for Feature Spotlight articles from curated insurance sources"""
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
                        'so_what': 'Review for Feature Spotlight feature story',
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
    """Generate Feature Spotlight from multiple source articles"""
    try:
        data = request.json
        articles = data.get('articles', [])
        month = data.get('month', 'january')

        if len(articles) < 3:
            return jsonify({'success': False, 'error': 'At least 3 articles required'}), 400

        print(f"\n[API] Generating Feature Spotlight from {len(articles)} articles...")

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

        # Get humanization guidelines for spotlight section
        from config.brand_guidelines import get_humanization_guidelines
        humanization_guide = get_humanization_guidelines('spotlight')

        spotlight_system = f"""You are writing the "Feature Spotlight" section for BriteCo Brief, a newsletter for independent insurance agents.

{humanization_guide}

=== REAL EXAMPLES FROM PAST ISSUES (match this structure, voice, and depth) ===

EXAMPLE 1 - "Credit Ratings to Flood Protection: How the Government Shutdown Is Affecting the Insurance Industry":
On October 1, the US government effectively shut down as Republican and Democratic leaders disagreed on a bill that directed federal services funding into October and beyond. As the shutdown still looms, questions arise about just how much the effect will trickle down into various sectors, including the insurance industry.

"Longer shutdowns could directly and indirectly affect insurers as consumers and businesses adjust spending and investment decisions," said Insurance Journal, noting information from AM Best.

In the article, Ann Modica, director of credit rating criteria at AM Best, shared an even bigger issue: credit rating decline, which could affect policy rates going forward. "The most lingering impact on the US economy is likely to be through the erosion of confidence in the effectiveness of US political institutions and the resulting impact on the country's sovereign credit ratings."

Flood Protection Has Come to a Halt, Too
Another unfortunate turn of events coinciding with the government shutdown is that the National Flood Insurance Program (NFIP), run by FEMA, also expired on October 1. With Congress out of session, there's no means to renew it.

This means no policies will be rolled over and no new ones sold, which could end up having grave effects. There will be coverage lapses for policyholders during a traditionally active time of year for hurricanes as well as a halting of real estate transactions that would depend on homeowners having flood protection. "About 1,300 property sales per day and about 40,000 closings per month are impacted, according to the National Association of Realtors (NAR)," says Insurance Journal.

Insurance News Net reports that more than 4.7 million Americans are current policyholders through NFIP. The article also notes that without a quick renewal of the program, "FEMA's borrowing authority from the US Treasury would shrink from $30.425 billion to just $1 billion, drastically limiting its ability to pay claims after a major hurricane or flood."

Implications for Insurance Agents
The shutdown's ripple effects are particularly acute for insurance agents. With NFIP business stalled, access to cross-sell or renew flood policies will be lost via the federal program, and there could be growing customer frustration as buyers, sellers, and mortgage lenders seek explanations for closing delays tied to unavailable federal flood coverage.
One recommendation is to pivot toward private flood insurance if available and to inform clients about differences in coverage, rates, and availability.

EXAMPLE 2 (structure only) - "20 Years After Hurricane Katrina: The Ongoing Impact on Insurance":
[Opened with the news hook and why it matters today]
[H3: "Better Models Have Eyes on the Storms" - specific data about $14.6 billion investments, geocoding improvements]
[H3: "Updated Policy Wording & Claims Handling Fill Gaps" - practical changes post-Katrina]
[H3: "Innovations Are Quickly Dictating the Future" - drones, AI, geospatial tools, with named companies like Travelers]
[Closed with agent implications and a forward-looking quote]

=== END EXAMPLES ===

WRITING STYLE (match the examples above):
- Use active voice and contractions (don't, won't, it's)
- Include DIRECT QUOTES from named people with their titles (e.g., "Ann Modica, director of credit rating criteria at AM Best, shared...")
- Use specific dollar amounts, percentages, and statistics -- never round or approximate
- Vary sentence length -- mix short punchy sentences with longer explanatory ones
- Give each subsection an H3 heading that's descriptive and engaging
- AVOID: "landscape", "navigate", "leverage", "robust", "comprehensive", "various factors", "in today's ever-evolving"
- Start some sentences with "And" or "But" for natural flow"""

        spotlight_prompt = f"""Analyze these {len(articles)} related articles and create a comprehensive, in-depth feature story:

{article_summaries}

Write a detailed spotlight article with:
- First line: A compelling headline/subheader (max 15 words) -- make it specific and descriptive, not generic
- Then 4-5 paragraphs with H3 subheadings that break the story into clear subtopics
- Each paragraph should be 3-5 sentences with SPECIFIC data, statistics, and DIRECT QUOTES from sources (with attribution)
- Include hyperlinks to source articles using markdown format [link text](URL)
- End with "AGENT TAKEAWAY:" followed by 3-4 bullet points of actionable insights

Target: 500-600 words. Be thorough and factual. Include at least 3-5 hyperlinks to source articles throughout the text.

Output as plain text - headline on first line, then paragraphs separated by blank lines (with H3 subheadings), then agent takeaway section at the end."""

        result = claude_client.generate_content(
            prompt=spotlight_prompt,
            system_prompt=spotlight_system,
            model="claude-opus-4-5-20251101",
            temperature=0.5,
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

        # Convert plain text paragraphs to HTML with proper formatting
        # Split by double newlines (paragraph breaks)
        paragraphs = [p.strip() for p in body_text.split('\n\n') if p.strip()]

        # Convert markdown links [text](url) to HTML links with blue styling
        import re
        def convert_links(text):
            return re.sub(
                r'\[([^\]]+)\]\(([^)]+)\)',
                r'<a href="\2" target="_blank" style="color: #0066cc; text-decoration: underline;">\1</a>',
                text
            )

        # Build HTML body with proper paragraph tags and spacing
        html_body = ''
        for p in paragraphs:
            p_with_links = convert_links(p)
            html_body += f'<p style="margin: 0 0 16px 0; line-height: 1.7;">{p_with_links}</p>'

        # Build simple structure - body as HTML
        spotlight_content = {
            'subheader': subheader,
            'body': html_body,
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

@app.route('/api/fetch-article-metadata', methods=['POST'])
def fetch_article_metadata():
    """Lightweight endpoint: fetch only title/description/publisher from a URL (no AI analysis)."""
    try:
        data = request.json
        url = data.get('url', '').strip()
        if not url:
            return jsonify({'title': '', 'description': '', 'publisher': ''}), 200

        is_valid, error = validate_url(url)
        if not is_valid:
            return jsonify({'title': '', 'description': '', 'publisher': '', 'error': error}), 200

        session = requests.Session()
        session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Sec-Fetch-User': '?1',
            'Cache-Control': 'max-age=0',
        })

        resp = session.get(url, timeout=10, allow_redirects=True)
        resp.raise_for_status()
        # Cap response size to 2MB to prevent DoS
        if len(resp.content) > 2 * 1024 * 1024:
            return jsonify({'title': '', 'description': '', 'publisher': '', 'error': 'Response too large'}), 200
        soup = BeautifulSoup(resp.text, 'html.parser')

        # Title
        title = ''
        og_title = soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            title = og_title['content']
        elif soup.title and soup.title.string:
            title = soup.title.string

        # Description
        description = ''
        og_desc = soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            description = og_desc['content']
        else:
            meta_desc = soup.find('meta', attrs={'name': 'description'})
            if meta_desc and meta_desc.get('content'):
                description = meta_desc['content']

        # Publisher
        publisher = ''
        og_site = soup.find('meta', property='og:site_name')
        if og_site and og_site.get('content'):
            publisher = og_site['content']
        else:
            from urllib.parse import urlparse
            publisher = urlparse(url).netloc.replace('www.', '')

        return jsonify({'title': title.strip(), 'description': description.strip(), 'publisher': publisher.strip()})
    except Exception as e:
        print(f"[API] fetch-article-metadata error: {e}")
        return jsonify({'title': '', 'description': '', 'publisher': ''}), 200


@app.route('/api/fetch-article', methods=['POST'])
def fetch_article():
    """Fetch and analyze an article from a user-provided URL using web scraping + OpenAI"""
    try:
        data = request.json
        url = data.get('url', '').strip()
        section = data.get('section', 'general')  # claims, roundup, spotlight, tips

        if not url:
            return jsonify({'success': False, 'error': 'URL is required'}), 400

        is_valid, error = validate_url(url)
        if not is_valid:
            return jsonify({'success': False, 'error': error}), 400

        print(f"\n[API] Fetching article from URL: {url}")
        print(f"  - Section: {section}")

        # Step 1: Fetch the webpage content using a session (handles cookies/redirects)
        session = requests.Session()
        session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Sec-Fetch-User': '?1',
            'Cache-Control': 'max-age=0',
        })

        try:
            response = session.get(url, timeout=15)
            response.raise_for_status()
        except requests.exceptions.RequestException as e:
            print(f"[API] Direct fetch failed ({str(e)}), falling back to AI web reader...")
            from urllib.parse import urlparse
            domain = urlparse(url).netloc.replace('www.', '')

            # Fallback: use OpenAI Responses API with web search to read the URL
            try:
                ai_prompt = f"""Read and analyze the article at this URL: {url}

Extract and return a JSON object with:
{{
    "title": "The article's headline",
    "description": "A 2-3 sentence summary of the article's main points",
    "publisher": "{domain}",
    "snippet": "A longer summary (4-5 sentences) with key facts and data points",
    "industry_data": "Any specific statistics, percentages, or data mentioned (or empty string if none)",
    "agent_implications": "How this news could relate to insurance agents (2-3 sentences, or empty if not relevant)",
    "content_type": "news"
}}

Return ONLY the JSON object, no other text."""

                ai_response = openai_client.client.responses.create(
                    model="gpt-4o",
                    tools=[{"type": "web_search"}],
                    input=ai_prompt,
                )
                result_text = ai_response.output_text.strip()

                if result_text.startswith('```'):
                    result_text = result_text.split('```')[1]
                    if result_text.startswith('json'):
                        result_text = result_text[4:]
                    result_text = result_text.strip()

                article_data = json.loads(result_text)
                article_data['url'] = url
                article_data['source_url'] = url
                article_data['headline'] = article_data.get('title', '')
                article_data['so_what'] = article_data.get('agent_implications', '')
                article_data['isCustomLink'] = True

                print(f"[API] AI fallback succeeded: {article_data.get('title', 'Unknown')}")
                return jsonify({
                    'success': True,
                    'article': article_data,
                    'generated_at': datetime.now().isoformat()
                })
            except Exception as ai_err:
                print(f"[API] AI fallback also failed: {str(ai_err)}")
                # Last resort: add with URL-derived info
                return jsonify({
                    'success': True,
                    'article': {
                        'title': url.split('/')[-1].replace('-', ' ').title()[:80],
                        'headline': url,
                        'snippet': 'Article content could not be fetched automatically. The link has been added for reference.',
                        'url': url,
                        'publisher': domain,
                        'impact': 'CUSTOM',
                        'isCustomLink': True
                    }
                })

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
        search_query = f"P&C insurance news {month} {datetime.now().year} ({sources_list})"

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

        # Build search query for practical agent job tips
        search_query = f"independent insurance agent practical tips actionable advice how to help clients {month} {datetime.now().year}"

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
        search_query = f"property casualty insurance news trends regulations {month} {datetime.now().year} ({sources_list})"

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
    """Search for major insurance news for Feature Spotlight"""
    try:
        data = request.json
        month = data.get('month', 'january')
        exclude_urls = data.get('exclude_urls', [])

        print(f"\n[API] Searching for spotlight topics (month: {month})...")

        # Build search query for major insurance news
        sources_list = ' OR '.join([f'site:{s}' for s in INSURANCE_NEWS_SOURCES])
        search_query = f"major insurance news breaking P&C industry {month} {datetime.now().year} ({sources_list})"

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
            claims_style = get_humanization_guidelines('curious_claims')
            claims_system = f"""You are a master storyteller writing the "Curious Claims" section for BriteCo Brief, an insurance newsletter for independent agents.

{claims_style}

VOICE & STYLE RULES:
- Write in a conversational, engaging tone (playful, lightest touch)
- Use short paragraphs (2-3 sentences each)
- Make it feel like a story, not a report
- Include direct quotes from sources when available
- Use SPECIFIC names, places, and dollar amounts (not "a driver" but "Melissa Schlarb")
- AVOID: "In an interesting development...", "unique situation", "diverse nature of cases"
- End with a practical insurance takeaway agents can use

=== REAL EXAMPLES FROM PAST ISSUES (match this voice and quality) ===

EXAMPLE 1 - "It Was Raining Cats & Dogs (Sort Of)":
A driver in western North Carolina recently got the surprise of her life when she found a surprise guest in her passenger seat. As Melissa Schlarb traversed Route 74 near the Great Smoky Mountains National Park in November, a dead cat came crashing through her windshield. It was the work of a bald eagle flying overhead that either lost its grip or discarded its kill. The driver thankfully escaped injury, but her windshield -- not so much.
When Schlarb opened the repair claim with her insurance company, it was met with understandable shock and awe. "The first insurance person I spoke to said, 'You're going to be the talk of the whole division. We never hear stories like this,'" she told local ABC affiliate WLOS. Though, at this point, it's still unclear if her claim will be approved due to such a unique scenario.
According to AAA, "Wildlife doesn't generally carry liability coverage, so any damages will be your responsibility. If you hit an animal, only comprehensive insurance may cover your loss." Yet even while a comprehensive policy may cover an incident like hitting a deer in the road, an animal falling from the sky is whole new territory.

EXAMPLE 2 - "Believe It Or Not: Alien Abduction Insurance Exists":
The truth is out there, and it comes in the form of this novelty insurance policy. As reported by PropertyCasualty360.com, companies like the St. Lawrence Agency in Florida offer extra-terrestrial coverage, and people are buying it.
The boutique provider, nicknamed the "UFO Abduction Insurance Agency," has offered this unique coverage since 1987, selling 6,000 policies since 2019 alone. For a one-time fee of $20, a customer is protected by $10 million in coverage limits. If you can prove you were taken by aliens, St. Lawrence Agency will pay $1 a year ... for 10 million years.

EXAMPLE 3 - "Recording Studio Claim Goes Up in Smoke":
A court has found a musician will receive $2 million for losses incurred during a fire at a Memphis recording studio back in 2015. In 2014, businessman Christopher Brown and his firm, Tattooed Millionaire, acquired the House of Blues recording studio and took out a policy with Hanover for $10 million. Brown has since been convicted of insurance fraud and is currently serving a 27-month sentence.
A federal appeals court affirmed that just because one insured party commits fraud doesn't mean every claimant under the same policy gets penalized. This case serves as a big reminder for agents: If a policy covers multiple interests, misconduct by one insured may not undo coverage for all.

=== END EXAMPLES ==="""

            claims_prompt = f"""Write an engaging STORY about this claims case. Target: 350-400 words.

Article: {curious_claims_topic.get('title', 'Unknown')}
Source: {curious_claims_topic.get('url', 'N/A')}
Initial Summary: {curious_claims_topic.get('description', '')}

Structure your story as:
1. HOOK (1-2 sentences) - attention-grabbing opening
2. THE SETUP (2-3 sentences) - who, what, where
3. THE INCIDENT (3-4 sentences) - vivid details
4. THE TWIST (2-3 sentences) - what made it interesting
5. THE RESOLUTION (2-3 sentences) - insurance outcome
6. AGENT TAKEAWAY (2-3 sentences) - lesson for agents

Output the complete story as flowing prose, not as labeled sections."""

            claims_research = claude_client.generate_content(
                prompt=claims_prompt,
                system_prompt=claims_system,
                model="claude-opus-4-5-20251101",
                temperature=0.7,
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

                roundup_system = """You write headline-style news bullets for BriteCo Brief, an insurance newsletter for independent agents.

STYLE: Title Case throughout, one punchy sentence, with specific stats/numbers. Naturally embed a hyperlink.

REAL EXAMPLES (match this exact style):
"According to a New Survey, 83% of Americans Say They Would Drop Their Insurance Company After One Bad Claims Experience"
"Auto Insurance Rates Are Falling Due to Fewer Claims, with the National Average Down By 2% and Even Up to 6.6% in Some Markets"
"Insured Losses for Natural Disasters Hit $108 Billion Globally in 2025, Down from $147 Billion in 2024 Due to Less US Hurricane Landfalls"
"Most Property Owners Are Now Paying 7% of Their Total Monthly Costs Towards Home Insurance, While Some Areas Like Miami Are Paying 13.1%"
"As Driverless Cars Become More Common & Human Error Decreases, Expect Fewer Auto Claims -- About 30-40% Less"
"Small Hail Stones Are Leading to More Home Insurance Claims; Stones Measuring Even 1 Inch Can Cause Damage and Premature Aging of Roofs"

RULES: Title Case. ONE sentence. Include specific numbers/percentages/dollar amounts. Never generic. Embed hyperlink as [Source Name](URL)."""

                roundup_prompt = f"""Write a headline-style news bullet for this article. Embed a hyperlink to [{source_name}]({url}).

Article: {topic.get('title', 'Unknown')}
Summary: {topic.get('description', '')}

Output ONLY the bullet text, nothing else."""

                roundup_result = claude_client.generate_content(
                    prompt=roundup_prompt,
                    system_prompt=roundup_system,
                    model="claude-opus-4-5-20251101",
                    temperature=0.5,
                    max_tokens=150
                )
                roundup_items.append({
                    'summary': roundup_result['content'].strip(),
                    'url': url,
                    'source': source_name
                })
            research_results['roundup'] = roundup_items
            print(f"    Roundup research complete: {len(roundup_items)} items")

        # Use pre-generated Feature Spotlight content from Step 2B
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

                tips_style = get_humanization_guidelines('agent_advantage')
                tips_system = f"""You write the "Agent Advantage" section for BriteCo Brief, an insurance newsletter for independent agents. This section provides practical, job-related tips agents can use right away — like how to use AI in their workflow, how to talk to customers about price hikes, how to help niche clients (rideshare drivers, small business owners), or how to grow their book of business. Tips should be grounded in the source article's findings.

{tips_style}

VOICE & STYLE:
- Lead the intro with a SPECIFIC statistic or finding, name the source
- Use direct quotes from sources (with attribution)
- Use contractions naturally (don't, won't, you'll)
- Keep tips practical -- something an agent can DO TODAY
- Include real numbers, percentages, and dollar amounts
- Sound like a knowledgeable colleague giving advice, not a textbook
- AVOID: "It is important to maintain...", "Leverage your relationships...", "Navigate the landscape...", "In today's evolving..."

=== REAL EXAMPLES (match this voice exactly) ===

EXAMPLE 1 - "3 Tips for Staying in Business with Small Business":
[INTRO]
When J.D. Power released its 2025 U.S. Small Commercial Insurance Study, one big statistic stood out: Only 55% of small business owners said they "definitely will" renew insurance policies with their current provider. Just a year ago, that threshold was 61%.

[TIPS]
1. **Good service is key.** "Insurers that communicate well and provide a higher level of service can make huge inroads toward keeping customers," J.D. Power's Stephen Crewdson shared. Their report shows that 16% of respondents noted customer service as more important than premium quotes.

2. **Communication is a must.** Crewdson also suggested "a huge onus on insurers to bolster their outreach around rate increases." Clients want to "completely understand" why prices went up.

3. **Individualized attention is a game-changer.** Insurers who know the nuances of a customer's specific business have a significant advantage, leading to a 37% year-over-year renewal rate.

EXAMPLE 2 - "Making the Right Call: 5 Ways to Better Connect with Clients":
[INTRO]
Policyholders often feel blindsided when a claim is denied, especially if the first notice is a formal letter they didn't anticipate receiving. Claims Journal says a simple phone call before the letter goes out can dramatically reduce misunderstandings, mistrust, and even lawsuits.

[TIPS]
1. **Advocate for Pre-Letter Calls.** Encourage claims partners to call insureds before sending formal denial or non-renewal letters.
2. **Prepare Clients.** Let clients know a call may be coming. Encourage them to stay calm, ask questions, and share any new facts.
3. **Anticipate Common Objections.** Help insureds understand decisions by addressing typical concerns like "Why isn't this covered?"

=== END EXAMPLES ==="""

                tips_prompt = f"""Create the "Agent Advantage" section based on this article.

ARTICLE:
Title: {topic.get('title', 'Unknown')}
Summary: {topic.get('description', topic.get('snippet', ''))}
Source: {topic.get('publisher', 'Industry Source')}

OUTPUT FORMAT:
[INTRO]
2-4 sentences with a specific stat hook from the article.

[TIPS]
1. **Bold Mini-Title.**
Supporting sentences with specifics and quotes.

(3-5 tips total)

Output ONLY the intro and tips in this format, nothing else."""

                tips_result = claude_client.generate_content(
                    prompt=tips_prompt,
                    system_prompt=tips_system,
                    model="claude-opus-4-5-20251101",
                    temperature=0.6,
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
            intro_system = f"""You are the copywriter for BriteCo Brief, a newsletter for independent insurance agents.

=== REAL EXAMPLES FROM PAST ISSUES (match this conversational voice) ===

"Thank you to everyone who completed our annual independent agent survey and vied for the chance to win a $200 gift card. We have now picked our winners. Keep reading to find out if you are a recipient and get the latest on the homeowners insurance crisis that's still wreaking havoc on the industry."

"It's hard to believe it's been 20 years since Hurricane Katrina caused one of the biggest catastrophes in US history and had an astronomical impact on insurance. We look at how the industry is better prepared today, provide tips on retaining small business customers, and examine the curious world of alien abduction insurance."

"From all of us at BriteCo, we are wishing you a very happy holiday season! As you make your list and check it twice, we wanted to remind you of one important item to not forget: filling out our brief Independent Agent Survey."

"We want to hear from you about how the homeowners insurance crisis is impacting your business. Fill out our brief Independent Agent Survey and you could be one of three winners to get a $200 gift card. Keep reading for the latest industry developments and learn how agents have an advantage."

=== END EXAMPLES ===

VOICE:
- Conversational and warm -- like writing to a colleague
- Use contractions naturally (it's, we're, you'll)
- AVOID generic openings like "Welcome to another edition" or "In this month's newsletter"
- Start with something SPECIFIC -- a stat, a question, a timely reference, or a direct address
- AVOID: "landscape", "navigate", "leverage", "robust", "comprehensive", "in today's ever-evolving"

{style_guide}"""

            intro_prompt = f"""Write a brief, welcoming introduction for the {month.capitalize()} edition.

Requirements:
- 2-4 sentences, maximum 75 words
- Reference something specific happening this month or tease specific content inside

Output ONLY the introduction text, no labels or formatting."""

            intro_result = claude_client.generate_content(
                prompt=intro_prompt,
                system_prompt=intro_system,
                model="claude-opus-4-5-20251101",
                temperature=0.7,
                max_tokens=150
            )
            sections['introduction'] = intro_result['content'].strip()

        # Generate Brite Spot (max 100 words) - auto-generate if no topic provided
        if not brite_spot_topic:
            print("  - Auto-generating Brite Spot (no topic provided)...")
            brite_spot_style = get_humanization_guidelines('brite_spot')
            auto_bs_system = f"""You are the copywriter for BriteCo Brief newsletter, writing the "Brite Spot" section.

=== REAL EXAMPLES FROM PAST ISSUES (match this warm, direct voice) ===

"As 2025 winds down, we wanted to wish you and yours a very happy holiday season and thank you for another great year of partnership. We value your contributions towards our mission of helping clients protect their jewelry and events. Here's to another great year working together in 2026!"

"We want to prioritize the next wave of POS integrations and need your help to do so. Please fill out our quick and easy form and tell us your preferred point-of-sale system. When you do, you'll be entered to win a $50 gift card!"

"A new J.D. Power study has found that 47% of homeowners saw premium increases in the past year, the highest jump in over a decade. You can protect your clients from a jewelry claim that sparks a higher homeowners premium or non-renewal by switching them from an HO rider/floater to a BriteCo stand-alone policy."

=== END EXAMPLES ===

{brite_spot_style}

VOICE:
- Warm, genuine, not corporate or salesy
- Use "we" and "you" frequently
- AVOID: "leverage", "robust", "innovative", "excited to announce"

{style_guide}"""

            auto_bs_prompt = f"""Write a brief "Brite Spot" section for the {month.capitalize()} edition thanking agents for their partnership and highlighting BriteCo's value.

Requirements:
- Maximum 75 words
- Warm, genuine tone
- Mention partnership and supporting clients
- Include a subtle call to action

Output ONLY the text, no title or labels."""

            try:
                auto_bs_result = claude_client.generate_content(
                    prompt=auto_bs_prompt,
                    system_prompt=auto_bs_system,
                    model="claude-opus-4-5-20251101",
                    temperature=0.6,
                    max_tokens=150
                )
                sections['brite_spot'] = auto_bs_result['content'].strip()
                print(f"    Auto-generated Brite Spot: {len(sections['brite_spot'].split())} words")
            except Exception as e:
                print(f"    Error auto-generating Brite Spot: {e}")
                sections['brite_spot'] = f"Thank you for your continued partnership with BriteCo. We're committed to helping you and your clients protect what matters most. Reach out to your BriteCo rep anytime — we're here to help."

        if brite_spot_topic:
            print("  - Generating Brite Spot...")
            brite_spot_style = get_humanization_guidelines('brite_spot')
            brite_spot_system = f"""You are the copywriter for BriteCo Brief newsletter, writing the "Brite Spot" section.

=== REAL EXAMPLES FROM PAST ISSUES (match this warm, direct voice) ===

EXAMPLE 1 - Survey Winners:
"We are happy to announce the winners of our yearly independent agent survey. Three agents won $200 gift cards just for completing the form. BriteCo congratulates: Clay Wadsworth of PolicyWatch Agency, Round Rock, Texas; Sean Hallihan of The Olderman & Hallihan Agency Inc., Ansonia, Connecticut; Jessica Gephart of 643 Insurance, Chandler, Arizona. Not surprising...our survey found that nearly two-thirds (63%) of agents said they had seen 75% or more of their clients experience a premium increase in 2025."

EXAMPLE 2 - Agent Testimonial:
"We recently met Bran Sorensen of Fine Insurance Group at the iiab Arizona conference in Scottsdale. She shares why her team trusts BriteCo. 'Hi, I'm Bran with the Fine Insurance Group, and we use BriteCo quite often. We love it because the service is wonderful. It's always fast and productive. I absolutely love their appraisal system, where if you have an older appraisal, they will appraise the product for a great price.'"

EXAMPLE 3 - Holiday Message:
"As 2025 winds down, we wanted to wish you and yours a very happy holiday season and thank you for another great year of partnership. We value your contributions towards our mission of helping clients protect their jewelry and events. Here's to another great year working together in 2026!"

EXAMPLE 4 - HO Crisis + BriteCo Benefits:
"A new J.D. Power study has found that 47% of homeowners saw premium increases in the past year, the highest jump in over a decade. You can protect your clients from a jewelry claim that sparks a higher homeowners premium or non-renewal by switching them from an HO rider/floater to a BriteCo stand-alone policy."

=== END EXAMPLES ===

{brite_spot_style}

VOICE:
- Warm, supportive, genuine tone -- not corporate or salesy
- Use contractions naturally (we're, you'll, don't)
- Sound like a real person writing to colleagues -- warm but professional
- Use "we" and "you" frequently
- AVOID: "leverage", "robust", "comprehensive", "cutting-edge", "innovative", "excited to announce"

{style_guide}"""

            brite_spot_prompt = f"""Write the "Brite Spot" section about: {brite_spot_topic}

Requirements:
- Maximum 100 words
- Lead with the benefit to agents or a specific fact/stat
- Include a clear call to action
- Be SPECIFIC about benefits (exact percentages, features, names)

Output ONLY the Brite Spot text, no title or labels."""

            brite_spot_result = claude_client.generate_content(
                prompt=brite_spot_prompt,
                system_prompt=brite_spot_system,
                model="claude-opus-4-5-20251101",
                temperature=0.6,
                max_tokens=200
            )
            sections['brite_spot'] = brite_spot_result['content'].strip()

        # Generate Curious Claims from research
        if research.get('curious_claims'):
            print("  - Writing Curious Claims section...")
            claims_style = get_humanization_guidelines('curious_claims')
            claims_gen_system = f"""You are the copywriter for BriteCo Brief newsletter, writing the "Curious Claims" section.

{claims_style}

VOICE:
- Playful, storytelling tone (puns and wordplay welcome)
- Open with an attention-grabbing hook
- Use specific details: "Melissa Schlarb traversed Route 74..." not "A driver was traveling..."
- Include telling details that make the story memorable
- Can show amusement at absurd situations
- Include direct quotes from sources when possible
- AVOID: "interesting development", "unique situation", "diverse nature of cases", "in the world of insurance"

=== REAL EXAMPLES OF CONDENSED CURIOUS CLAIMS (match this voice exactly) ===

EXAMPLE 1:
<p>Earlier this month, hundreds of drivers in Colorado found themselves stalled after unknowingly pumping their cars full of contaminated gasoline. A number of gas stations, including King Soopers and Costco locations, had received unleaded fuel supplies from distributor Sinclair that were accidentally mixed with diesel fuel.</p>
<p>According to Kelly Blue Book, diesel can ruin a car's engine by affecting fuel injectors, filters, pumps, and even the exhaust system. The state has received more than 200 complaints, with some citing repair costs of $3,000 or more. But will it be covered? "If something happens that causes you to incur property damage, then that could potentially be covered by the policy, because it was something external that caused the damage to the car," said one source quoted by PropertyCasualty360.</p>

EXAMPLE 2:
<p>The truth is out there, and it comes in the form of this novelty insurance policy. Companies like the St. Lawrence Agency in Florida offer extra-terrestrial coverage, and people are buying it. The boutique provider has offered this unique coverage since 1987, selling 6,000 policies since 2019 alone.</p>
<p>For a one-time fee of $20, a customer is protected by $10 million in coverage limits. The catch? If you can prove you were taken by aliens, St. Lawrence Agency will pay $1 a year ... for 10 million years. It may sound totally sci-fi, but the firm has completed two successful payouts.</p>

=== END EXAMPLES ===

CRITICAL: Write like the examples above -- specific names, dollar amounts, quotes from real sources, and a storytelling voice. NEVER write generic summaries.

{style_guide}"""

            claims_gen_prompt = f"""## RESEARCH BRIEFING
{research['curious_claims']}

Write the "Curious Claims" section based on this research.

Requirements:
- EXACTLY 2-3 distinct paragraphs (each wrapped in <p> tags)
- Each paragraph should be 2-4 sentences
- Maximum 200 words total
- Use vivid, specific details (names, places, dollar amounts)
- End with a practical takeaway for agents

PARAGRAPH STRUCTURE:
- Paragraph 1: The hook and main story setup (who, what, where)
- Paragraph 2: The twist/absurdity/resolution (what happened, why it's memorable)
- Paragraph 3 (optional): Brief agent takeaway or amusing insight

OUTPUT FORMAT:
<p>First paragraph content here...</p>
<p>Second paragraph content here...</p>
<p>Optional third paragraph...</p>

Output ONLY the paragraphs in <p> tags, no title or labels."""

            claims_result = claude_client.generate_content(
                prompt=claims_gen_prompt,
                system_prompt=claims_gen_system,
                model="claude-opus-4-5-20251101",
                temperature=0.65,
                max_tokens=400
            )
            sections['curious_claims'] = claims_result['content'].strip()

        # News Roundup is already formatted as bullet points from research
        if research.get('roundup'):
            sections['roundup'] = research['roundup']

        # Use pre-generated Feature Spotlight content (already written in Step 2B)
        # Keep the object structure for frontend to display properly
        if research.get('spotlight'):
            print("  - Formatting Feature Spotlight section...")
            spotlight_data = research['spotlight']

            if isinstance(spotlight_data, dict):
                # Keep the full object structure for frontend display
                sections['spotlight'] = spotlight_data
                sections['spotlight_subheader'] = spotlight_data.get('subheader', '')
                sections['spotlight_sources'] = spotlight_data.get('sources', [])
            else:
                # Fallback if it's already a string - wrap in object structure
                sections['spotlight'] = {
                    'subheader': 'Feature Spotlight',
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

            prompt_request = f"""Create a text-to-image prompt for an insurance newsletter image.

Section: {section_name}
Title: "{title}"
Content: "{content}..."

Requirements:
- Photorealistic, professional photography style (NOT cartoon, NOT illustration, NOT digital art)
- Stock photo aesthetic - like images from Shutterstock or Getty Images
- Blue/teal color accents where appropriate (BriteCo brand colors)
- No text overlays in the image
- Suitable for professional email newsletter
- Clean, well-lit, high-quality photography look

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


@app.route('/api/enhance-image-prompt', methods=['POST'])
def enhance_image_prompt():
    """Enhance a rough image description into a detailed, optimized image generation prompt"""
    try:
        data = request.json
        prompt = data.get('prompt', '')
        if not prompt:
            return jsonify({'success': False, 'error': 'Prompt required'}), 400

        if not claude_client:
            return jsonify({'success': False, 'error': 'Claude client not available'}), 500

        system_prompt = """You are an expert image prompt engineer. Take the user's rough description and transform it into a highly detailed, optimized prompt for AI image generation.

RULES:
- Be specific about composition, lighting, color palette, and style
- Specify "professional photograph" or "digital illustration" style
- Include mood and atmosphere details
- Add details about perspective and framing
- NEVER include text, words, letters, or watermarks in the image description
- Keep the enhanced prompt under 200 words
- Output ONLY the enhanced prompt, nothing else"""

        result = claude_client.generate_content(
            prompt=f"Enhance this image prompt for newsletter use:\n\n{prompt}",
            system_prompt=system_prompt,
            max_tokens=300,
            temperature=0.7
        )

        enhanced = result.get('content', '').strip()

        return jsonify({
            'success': True,
            'enhanced_prompt': enhanced,
            'original_prompt': prompt
        })

    except Exception as e:
        print(f"[API ERROR] Enhance prompt: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/generate-images', methods=['POST'])
def generate_images():
    """Generate images for newsletter sections using provided or auto-generated prompts (matches venue-voice)"""
    try:
        data = request.json

        # Check if Gemini is available
        if not gemini_client or not gemini_client.is_available():
            return jsonify({
                'success': False,
                'error': 'Gemini API not configured. Please add GOOGLE_AI_API_KEY to your .env file. Get a key from https://aistudio.google.com/app/apikey'
            }), 503

        # Handle single-image request (from special section)
        single_prompt = data.get('prompt')
        single_section = data.get('section')
        if single_prompt and single_section:
            print(f"\n[API] Single image request for {single_section}")
            try:
                image_result = gemini_client.generate_image(
                    prompt=single_prompt,
                    aspect_ratio="16:9"
                )
                image_data = image_result.get('image_base64', image_result.get('image_data', ''))
                if image_data:
                    return jsonify({
                        'success': True,
                        'image_data': image_data,
                        'images': {single_section: f"data:image/png;base64,{image_data}"}
                    })
                else:
                    return jsonify({'success': False, 'error': 'No image data returned'})
            except Exception as e:
                print(f"  [ERROR] Single image generation failed: {e}")
                return jsonify({'success': False, 'error': str(e)})

        # Handle sections dict format (from special section)
        sections = data.get('sections', {})
        if sections and not data.get('prompts'):
            prompts = sections
        else:
            prompts = data.get('prompts', {})  # Pre-generated or user-edited prompts

        print(f"\n[API] Generating images with Nano Banana (Gemini)...")
        print(f"[API] Received {len(prompts)} prompts")

        images = {}

        # Generate image for each prompt
        for section_name, prompt in prompts.items():
            safe_print(f"  [{section_name.upper()}] Prompt: {prompt[:80]}...")

            # Determine aspect ratio based on section
            # All section images are now full-width landscape (16:9)
            aspect_ratio = "16:9"

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

                    # Section-specific image sizes - reduced from 570px to avoid
                    # Gmail mobile using intrinsic dimensions for layout calculation
                    IMAGE_SIZES = {
                        'briteSpot': (480, 270),    # Full width landscape
                        'claims': (480, 270),        # Full width landscape
                        'spotlight': (480, 270),     # Full width landscape
                        'tips': (480, 175),          # Full width, shorter than standard
                    }
                    target_width, target_height = IMAGE_SIZES.get(section_name, (570, 320))

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
- Feature Spotlight
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
- Feature Spotlight (deep dive on trending topic)
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
        welcome_content = data.get('welcome_content', '')
        claims_content = data.get('claims_content', '')
        roundup_content = data.get('roundup_content', '')
        spotlight_content = data.get('spotlight_content', '')
        tips_content = data.get('tips_content', '')
        brite_spot_content = data.get('brite_spot_content', '')

        print(f"\n[API] Running brand check...")

        # Combine all content for checking
        full_content = f"""
WELCOME SECTION:
{welcome_content}

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

IMPORTANT: Skip over hyperlinks and URLs - do not flag them as issues. Hyperlinks in formats like [text](url) or <a href="...">text</a> should be left as-is.

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
                    safe_print(f"[API] Email sent successfully")
                else:
                    error_msg = f"SendGrid returned status {response.status_code}"
                    safe_print(f"[API] {error_msg}")
                    errors.append(error_msg)

            except Exception as email_error:
                error_msg = f"Failed to send email: {str(email_error)}"
                safe_print(f"[API] {error_msg}")
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

        safe_print(f"[API] Google Docs credentials configured: {bool(creds_json)}")

        if not creds_json:
            return jsonify({
                "success": False,
                "error": "Google Docs credentials not configured. Set GOOGLE_DOCS_CREDENTIALS via Secret Manager."
            }), 500

        # Parse credentials
        try:
            creds_data = json.loads(creds_json)
            credentials = service_account.Credentials.from_service_account_info(
                creds_data,
                scopes=['https://www.googleapis.com/auth/documents', 'https://www.googleapis.com/auth/drive']
            )
        except json.JSONDecodeError as e:
            safe_print(f"[API] JSON parse error in credentials: {e}")
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

        # First, verify access to the folder
        safe_print(f"[API] Checking access to folder: {GOOGLE_DRIVE_FOLDER_ID}")
        try:
            folder_check = drive_service.files().get(
                fileId=GOOGLE_DRIVE_FOLDER_ID,
                fields='id, name, driveId',
                supportsAllDrives=True
            ).execute()
            safe_print(f"[API] Folder access OK: {folder_check.get('name')}, driveId: {folder_check.get('driveId', 'None (regular folder)')}")
        except Exception as folder_err:
            safe_print(f"[API] Folder access check failed: {folder_err}")
            return jsonify({
                "success": False,
                "error": f"Cannot access Google Drive folder. Ensure the service account has access. Error: {str(folder_err)}"
            }), 500

        # Create a new Google Doc directly in the shared folder using Drive API
        file_metadata = {
            'name': title,
            'mimeType': 'application/vnd.google-apps.document',
            'parents': [GOOGLE_DRIVE_FOLDER_ID]
        }

        created_file = drive_service.files().create(
            body=file_metadata,
            fields='id',
            supportsAllDrives=True
        ).execute()

        doc_id = created_file.get('id')
        doc_url = f"https://docs.google.com/document/d/{doc_id}/edit"

        safe_print(f"[API] Created Google Doc in folder: {doc_id}")

        # Build document content from newsletter sections
        requests_list = []

        # Helper to convert HTML to plain text
        def html_to_plain_text(html_content):
            if not html_content:
                return ''
            import re
            text = str(html_content)
            # Convert links: <a href="url">text</a> -> text (url)
            text = re.sub(r'<a[^>]*href=["\']([^"\']*)["\'][^>]*>([^<]*)</a>', r'\2 (\1)', text)
            # Convert <li> to bullet points
            text = re.sub(r'<li[^>]*>', '• ', text)
            text = re.sub(r'</li>', '\n', text)
            # Convert <p> to paragraphs
            text = re.sub(r'<p[^>]*>', '', text)
            text = re.sub(r'</p>', '\n\n', text)
            # Remove all other HTML tags
            text = re.sub(r'<[^>]+>', '', text)
            # Decode HTML entities
            text = text.replace('&amp;', '&')
            text = text.replace('&lt;', '<')
            text = text.replace('&gt;', '>')
            text = text.replace('&quot;', '"')
            text = text.replace('&#39;', "'")
            text = text.replace('&nbsp;', ' ')
            # Remove ** markdown bold markers
            text = re.sub(r'\*\*([^*]+)\*\*', r'\1', text)
            # Clean up whitespace
            text = re.sub(r'\n{3,}', '\n\n', text)
            return text.strip()

        # Helper to add text with formatting
        def add_text(text, bold=False, heading=False, index_offset=[1]):
            if not text:
                return
            # Convert HTML to plain text
            text = html_to_plain_text(text)
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

        def html_to_plain_text_keep_links(html):
            """Strip HTML tags EXCEPT <a> tags."""
            import re
            # Keep <a> tags but strip everything else
            result = re.sub(r'<br\s*/?\s*>', '\n', html)
            result = re.sub(r'</p>\s*<p[^>]*>', '\n\n', result)
            result = re.sub(r'<(?!/?a[ >])[^>]+>', '', result)
            result = result.replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>').replace('&nbsp;', ' ').replace('&#39;', "'").replace('&quot;', '"')
            return result.strip()

        def add_rich_text(html_val, bold=False, index_offset=[None]):
            """Insert text preserving <a> tag hyperlinks as Google Docs links."""
            import re
            if not html_val:
                return
            # Use the same index_offset as add_text by accessing add_text's default
            offset = add_text.__defaults__[2]
            if not html_val:
                return
            # Strip to plain text but keep <a> tags
            text_val = html_to_plain_text_keep_links(html_val)
            # Parse segments: plain text and links
            segments = []
            last_end = 0
            for m in re.finditer(r'<a\s+[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', text_val, re.IGNORECASE | re.DOTALL):
                if m.start() > last_end:
                    segments.append(('text', text_val[last_end:m.start()]))
                segments.append(('link', m.group(2), m.group(1)))
                last_end = m.end()
            if last_end < len(text_val):
                segments.append(('text', text_val[last_end:]))
            if not segments:
                segments = [('text', html_to_plain_text(html_val))]
            for seg in segments:
                if seg[0] == 'text':
                    plain = seg[1]
                    plain = re.sub(r'<[^>]+>', '', plain)
                    if not plain:
                        continue
                    requests_list.append({'insertText': {'location': {'index': offset[0]}, 'text': plain}})
                    if bold:
                        requests_list.append({'updateTextStyle': {'range': {'startIndex': offset[0], 'endIndex': offset[0] + len(plain)}, 'textStyle': {'bold': True}, 'fields': 'bold'}})
                    offset[0] += len(plain)
                elif seg[0] == 'link':
                    link_text = re.sub(r'<[^>]+>', '', seg[1])
                    link_url = seg[2]
                    if not link_text:
                        link_text = link_url
                    requests_list.append({'insertText': {'location': {'index': offset[0]}, 'text': link_text}})
                    requests_list.append({'updateTextStyle': {'range': {'startIndex': offset[0], 'endIndex': offset[0] + len(link_text)}, 'textStyle': {'link': {'url': link_url}, 'foregroundColor': {'color': {'rgbColor': {'red': 0.0, 'green': 0.506, 'blue': 0.506}}}}, 'fields': 'link,foregroundColor'}})
                    offset[0] += len(link_text)
            # Add newline
            requests_list.append({'insertText': {'location': {'index': offset[0]}, 'text': '\n'}})
            offset[0] += 1

        # Add newsletter sections
        add_text(title, heading=True)

        # Subject line & preheader (if provided)
        subject_line = data.get('subject_line', '')
        preheader_text = data.get('preheader', '')
        if subject_line:
            add_text('Subject Line:', bold=True)
            add_text(subject_line)
        if preheader_text:
            add_text('Preheader:', bold=True)
            add_text(preheader_text)

        if content.get('header_intro'):
            add_rich_text(content['header_intro'])

        # Note: Introduction section removed - BriteCo Brief header_intro is used instead

        if content.get('brite_spot'):
            add_text('The Brite Spot', bold=True)
            add_rich_text(content['brite_spot'])

        if content.get('curious_claims'):
            add_text('Curious Claims', bold=True)
            add_rich_text(content['curious_claims'])

        if content.get('roundup'):
            add_text('Insurance News Roundup', bold=True)
            if isinstance(content['roundup'], list):
                for item in content['roundup']:
                    bullet = item.get('summary', item) if isinstance(item, dict) else item
                    add_rich_text(f"• {bullet}")
            else:
                add_rich_text(content['roundup'])

        if content.get('spotlight'):
            add_text('Feature Spotlight', bold=True)
            spotlight = content['spotlight']
            if isinstance(spotlight, dict):
                if spotlight.get('subheader'):
                    add_text(spotlight['subheader'])
                if spotlight.get('h3s') and isinstance(spotlight['h3s'], list):
                    for h3 in spotlight['h3s']:
                        if isinstance(h3, dict):
                            title = h3.get('title', h3.get('h3', ''))
                            if title:
                                # Strip markdown # headers
                                import re
                                title = re.sub(r'^#{1,3}\s+', '', title)
                                add_text(title, bold=True)
                            body = h3.get('body', h3.get('content', ''))
                            if body:
                                add_rich_text(body)
                elif spotlight.get('body'):
                    add_rich_text(spotlight['body'])
            else:
                add_rich_text(str(spotlight))

        if content.get('agent_tips'):
            add_text('Agent Advantage', bold=True)
            tips = content['agent_tips']
            if isinstance(tips, dict) and tips.get('intro'):
                add_rich_text(tips['intro'])
                for i, tip in enumerate(tips.get('tips', []), 1):
                    if isinstance(tip, dict):
                        tip_title = tip.get('title', '')
                        tip_body = tip.get('tip', tip.get('content', ''))
                        if tip_title:
                            add_text(f"{i}. {tip_title}", bold=True)
                            if tip_body:
                                add_rich_text(tip_body)
                        else:
                            add_rich_text(f"{i}. {tip_body}")
                    else:
                        add_rich_text(f"{i}. {tip}")
            elif isinstance(tips, list):
                for i, tip in enumerate(tips, 1):
                    tip_text = tip.get('tip', tip) if isinstance(tip, dict) else tip
                    add_rich_text(f"{i}. {tip_text}")
            else:
                add_rich_text(str(tips))

        # Special Section (if included)
        if content.get('special_section'):
            ss = content['special_section']
            ss_title = ss.get('title', 'Special Section') if isinstance(ss, dict) else 'Special Section'
            ss_body = ss.get('body', str(ss)) if isinstance(ss, dict) else str(ss)
            add_text(ss_title, bold=True)
            add_rich_text(ss_body)

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
            body={'type': 'anyone', 'role': 'reader'},
            supportsAllDrives=True
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
                                safe_print(f"[API] Email sent successfully")
                            else:
                                error_msg = f"SendGrid returned status {response.status_code}"
                                email_errors.append(error_msg)
                                safe_print(f"[API] {error_msg}")

                        except Exception as email_error:
                            error_msg = f"Failed to send email: {str(email_error)}"
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

        safe_print(f"[API] SendGrid configured: {bool(sendgrid_api_key)}, sending to {len(recipients)} recipient(s)")

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

                # Use simpler Mail constructor for reliability
                message = Mail(
                    from_email=(from_email, from_name),
                    to_emails=recipient,
                    subject=f"Agent Newsletter ({month} {year}) - Ready for Review",
                    html_content=email_html
                )

                response = sg.send(message)
                safe_print(f"[API] Email sent successfully, status: {response.status_code}")
                emails_sent.append(recipient)
            except Exception as email_error:
                safe_print(f"[API] Failed to send email: {email_error}")
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
@app.route('/api/push-to-ontraport', methods=['POST'])
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
                "message": "Newsletter campaign created in Ontraport",
                "email_id": result.get('email_id'),
                "message_id": result.get('message_id'),
                "campaign_id": result.get('campaign_id'),
                "preview_url": result.get('preview_url'),
                "status": result.get('status', 'draft')
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
# NOT-GOOD-FIT TRACKING
# ============================================================================

NOT_GOOD_FIT_BLOB = 'feedback/not-good-fit.json'

@app.route('/api/not-good-fit', methods=['POST'])
def track_not_good_fit():
    """Track articles marked as 'not a good fit' for learning"""
    if not gcs_client:
        return jsonify({'success': False, 'error': 'GCS not available'}), 503
    try:
        article = request.json.get('article', {})
        if not article.get('url'):
            return jsonify({'success': False, 'error': 'Article URL required'}), 400

        bucket = gcs_client.bucket(GCS_BUCKET_NAME)
        blob = bucket.blob(NOT_GOOD_FIT_BLOB)

        entries = []
        generation = 0
        if blob.exists():
            blob.reload()
            generation = blob.generation
            data = json.loads(blob.download_as_text())
            entries = data.get('entries', [])

        if not any(e.get('url') == article['url'] for e in entries):
            entries.append({
                'url': article['url'],
                'title': article.get('title', ''),
                'publisher': article.get('publisher', ''),
                'markedAt': datetime.now(CHICAGO_TZ).isoformat()
            })
            blob.upload_from_string(
                json.dumps({'entries': entries}),
                content_type='application/json',
                if_generation_match=generation
            )

        return jsonify({'success': True, 'count': len(entries)})

    except Exception as e:
        safe_print(f"[NOT-GOOD-FIT] Error: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


# ============================================================================
# IMAGE HOSTING - GCS Upload
# ============================================================================

@app.route('/api/upload-images-to-gcs', methods=['POST'])
def upload_images_to_gcs():
    """Upload newsletter images to GCS and return public URLs"""
    if not gcs_client:
        return jsonify({'success': False, 'error': 'GCS not configured'}), 500

    try:
        data = request.json
        images = data.get('images', {})
        month = data.get('month', 'unknown')
        year = data.get('year', datetime.now().year)

        if not images:
            return jsonify({'success': False, 'error': 'No images provided'}), 400

        bucket = gcs_client.bucket(GCS_IMAGES_BUCKET)
        uploaded_urls = {}
        timestamp = datetime.now(CHICAGO_TZ).strftime('%Y%m%d-%H%M%S')

        for section, data_url in images.items():
            if not data_url or not data_url.startswith('data:image'):
                continue

            try:
                header, b64_data = data_url.split(',', 1)
                img_format = 'png'
                if 'jpeg' in header or 'jpg' in header:
                    img_format = 'jpg'
                elif 'webp' in header:
                    img_format = 'webp'

                image_bytes = base64.b64decode(b64_data)
                safe_section = section.replace('_', '-')
                filename = f"newsletters/{year}/{month.lower()}/{timestamp}-{safe_section}.{img_format}"

                blob = bucket.blob(filename)
                blob.upload_from_string(image_bytes, content_type=f'image/{img_format}')
                blob.make_public()
                uploaded_urls[section] = blob.public_url
                safe_print(f"[GCS] Uploaded {section} -> {blob.public_url}")

            except Exception as img_error:
                safe_print(f"[GCS] Error uploading {section}: {str(img_error)}")
                continue

        return jsonify({'success': True, 'urls': uploaded_urls, 'count': len(uploaded_urls)})

    except Exception as e:
        safe_print(f"[GCS UPLOAD] Error: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


# ============================================================================
# DRAFTS - GCS Auto-save
# ============================================================================

@app.route('/api/save-draft', methods=['POST'])
def save_draft():
    """Auto-save newsletter draft to GCS"""
    if not gcs_client:
        return jsonify({'success': False, 'error': 'GCS not available'}), 503
    try:
        # Use server-side session for user identity (don't trust client-sent savedBy)
        user = get_current_user()
        user_email = user.get('email', 'unknown') if user else 'unknown'
        saved_by = user_email.split('@')[0].replace('.', '-')

        data = request.get_json(force=True)  # force=True handles sendBeacon Content-Type
        month = data.get('month', 'unknown').lower()
        year = data.get('year', datetime.now().year)
        blob_name = f"drafts/{month}-{year}-{saved_by}.json"

        draft = {
            'month': month,
            'year': year,
            'currentStep': data.get('currentStep'),
            'generatedContent': data.get('generatedContent'),
            'generatedImages': data.get('generatedImages'),
            'imagePrompts': data.get('imagePrompts'),
            'selectedArticles': data.get('selectedArticles'),
            'specialSection': data.get('specialSection'),
            'subjectLine': data.get('subjectLine'),
            'preheader': data.get('preheader'),
            'reviewHTML': data.get('reviewHTML'),
            'skippedResearch': data.get('skippedResearch'),
            'lastSavedBy': user_email,
            'lastSavedAt': datetime.now(CHICAGO_TZ).isoformat()
        }

        bucket = gcs_client.bucket(GCS_BUCKET_NAME)
        blob = bucket.blob(blob_name)
        blob.upload_from_string(json.dumps(draft), content_type='application/json')
        return jsonify({'success': True, 'file': blob_name})

    except Exception as e:
        safe_print(f"[DRAFT SAVE ERROR] {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/list-drafts', methods=['GET'])
def list_drafts():
    """List all drafts from GCS"""
    if not gcs_client:
        return jsonify({'success': True, 'drafts': []})
    try:
        bucket = gcs_client.bucket(GCS_BUCKET_NAME)
        blobs = list(bucket.list_blobs(prefix='drafts/'))
        drafts = []
        for blob in blobs:
            if blob.name.endswith('.json'):
                data = json.loads(blob.download_as_text())
                drafts.append({
                    'filename': blob.name,
                    'month': data.get('month'),
                    'year': data.get('year'),
                    'currentStep': data.get('currentStep'),
                    'lastSavedBy': data.get('lastSavedBy'),
                    'lastSavedAt': data.get('lastSavedAt'),
                })
        drafts.sort(key=lambda d: d.get('lastSavedAt', ''), reverse=True)
        return jsonify({'success': True, 'drafts': drafts})
    except Exception as e:
        safe_print(f"[DRAFT LIST ERROR] {str(e)}")
        return jsonify({'success': True, 'drafts': []})


@app.route('/api/load-draft', methods=['GET'])
def load_draft():
    """Load a specific draft from GCS"""
    if not gcs_client:
        return jsonify({'success': False, 'error': 'GCS not available'}), 503
    try:
        filename = request.args.get('file')
        if not filename:
            return jsonify({'success': False, 'error': 'No file specified'}), 400
        if not validate_gcs_filename(filename, ['drafts/']):
            return jsonify({'success': False, 'error': 'Invalid filename'}), 400
        bucket = gcs_client.bucket(GCS_BUCKET_NAME)
        blob = bucket.blob(filename)
        if not blob.exists():
            return jsonify({'success': False, 'error': 'Draft not found'}), 404
        data = json.loads(blob.download_as_text())
        return jsonify({'success': True, 'draft': data})
    except Exception as e:
        safe_print(f"[DRAFT LOAD ERROR] {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/publish-draft', methods=['POST'])
def publish_draft():
    """Copy a draft from drafts/ to published/ in GCS with a versioned timestamp name"""
    user = get_current_user()
    if not user:
        return jsonify({'success': False, 'error': 'Not authenticated'}), 401
    if not gcs_client:
        return jsonify({'success': False, 'error': 'GCS not available'}), 503
    try:
        filename = request.json.get('file')
        if not filename:
            return jsonify({'success': False, 'error': 'No file specified'}), 400
        if not validate_gcs_filename(filename, ['drafts/']):
            return jsonify({'success': False, 'error': 'Invalid filename'}), 400
        bucket = gcs_client.bucket(GCS_BUCKET_NAME)
        source_blob = bucket.blob(filename)
        if not source_blob.exists():
            return jsonify({'success': False, 'error': 'Draft not found'}), 404
        # Use timestamped filename so each Ontraport push saves a new version
        timestamp = datetime.now().strftime('%Y%m%d-%H%M%S')
        base_name = filename.replace('drafts/', '', 1).replace('.json', '')
        published_name = f'published/{base_name}-{timestamp}.json'
        bucket.copy_blob(source_blob, bucket, published_name)
        # Keep the draft file intact so it can be reloaded/edited
        safe_print(f"[DRAFT] Published {filename} -> {published_name}")
        return jsonify({'success': True, 'file': published_name})
    except Exception as e:
        safe_print(f"[DRAFT PUBLISH ERROR] {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/list-published', methods=['GET'])
def list_published():
    """List all published newsletters from GCS"""
    if not gcs_client:
        return jsonify({'success': True, 'newsletters': []})
    try:
        bucket = gcs_client.bucket(GCS_BUCKET_NAME)
        blobs = list(bucket.list_blobs(prefix='published/'))
        newsletters = []
        for blob in blobs:
            if blob.name.endswith('.json'):
                data = json.loads(blob.download_as_text())
                gc = data.get('generatedContent', {})
                newsletters.append({
                    'filename': blob.name,
                    'month': data.get('month'),
                    'year': data.get('year'),
                    'lastSavedBy': data.get('lastSavedBy'),
                    'lastSavedAt': data.get('lastSavedAt'),
                    'sections': {
                        'news': {'title': gc.get('headerIntro', 'Newsletter')[:80] if gc.get('headerIntro') else 'Newsletter'},
                        'tip': {'title': gc.get('briteSpot', 'Brite Spot')[:80] if gc.get('briteSpot') else 'Brite Spot'},
                        'trend': {'title': gc.get('spotlight', 'Spotlight')[:80] if gc.get('spotlight') else 'Spotlight'},
                    }
                })
        newsletters.sort(key=lambda d: d.get('lastSavedAt', ''), reverse=True)
        return jsonify({'success': True, 'newsletters': newsletters})
    except Exception as e:
        safe_print(f"[PUBLISHED LIST ERROR] {str(e)}")
        return jsonify({'success': True, 'newsletters': []})


@app.route('/api/load-published', methods=['GET'])
def load_published():
    """Load a specific published newsletter from GCS"""
    if not gcs_client:
        return jsonify({'success': False, 'error': 'GCS not available'}), 503
    try:
        filename = request.args.get('file')
        if not filename:
            return jsonify({'success': False, 'error': 'No file specified'}), 400
        if not validate_gcs_filename(filename, ['published/']):
            return jsonify({'success': False, 'error': 'Invalid filename'}), 400
        bucket = gcs_client.bucket(GCS_BUCKET_NAME)
        blob = bucket.blob(filename)
        if not blob.exists():
            return jsonify({'success': False, 'error': 'Not found'}), 404
        data = json.loads(blob.download_as_text())
        return jsonify({'success': True, 'draft': data})
    except Exception as e:
        safe_print(f"[PUBLISHED LOAD ERROR] {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/delete-draft', methods=['DELETE'])
def delete_draft():
    """Delete a draft from GCS"""
    user = get_current_user()
    if not user:
        return jsonify({'success': False, 'error': 'Not authenticated'}), 401
    if not gcs_client:
        return jsonify({'success': True})
    try:
        filename = request.json.get('file')
        if not filename:
            return jsonify({'success': False, 'error': 'No file specified'}), 400
        if not validate_gcs_filename(filename, ['drafts/']):
            return jsonify({'success': False, 'error': 'Invalid filename'}), 400
        bucket = gcs_client.bucket(GCS_BUCKET_NAME)
        blob = bucket.blob(filename)
        if blob.exists():
            blob.delete()
        return jsonify({'success': True})
    except Exception as e:
        safe_print(f"[DRAFT DELETE ERROR] {str(e)}")
        return jsonify({'success': True})


@app.route('/api/delete-published', methods=['DELETE'])
def delete_published():
    """Delete a published newsletter from GCS"""
    if not gcs_client:
        return jsonify({'success': True})
    try:
        filename = request.json.get('file')
        if not filename:
            return jsonify({'success': False, 'error': 'No file specified'}), 400
        if not validate_gcs_filename(filename, ['published/']):
            return jsonify({'success': False, 'error': 'Invalid filename'}), 400
        bucket = gcs_client.bucket(GCS_BUCKET_NAME)
        blob = bucket.blob(filename)
        if blob.exists():
            blob.delete()
            safe_print(f"[PUBLISHED] Deleted {filename}")
        return jsonify({'success': True})
    except Exception as e:
        safe_print(f"[PUBLISHED DELETE ERROR] {str(e)}")
        return jsonify({'success': True})


# ============================================================================
# SAVED ARTICLES (Article Banking / Save for Later)
# ============================================================================

SAVED_ARTICLES_BLOB = 'saved-articles/global.json'

@app.route('/api/saved-articles', methods=['GET'])
def get_saved_articles():
    """Get all saved articles from GCS"""
    if not gcs_client:
        return jsonify({'success': True, 'articles': []})
    try:
        bucket = gcs_client.bucket(GCS_BUCKET_NAME)
        blob = bucket.blob(SAVED_ARTICLES_BLOB)
        if blob.exists():
            data = json.loads(blob.download_as_text())
            # Handle both old format (list) and new format ({articles: []})
            if isinstance(data, list):
                return jsonify({'success': True, 'articles': data})
            return jsonify({'success': True, 'articles': data.get('articles', [])})
        return jsonify({'success': True, 'articles': []})
    except Exception as e:
        safe_print(f"[SAVED ARTICLES] Error loading: {str(e)}")
        return jsonify({'success': True, 'articles': []})


@app.route('/api/saved-articles', methods=['POST'])
def add_saved_article():
    """Add an article to the saved articles list"""
    if not gcs_client:
        return jsonify({'success': False, 'error': 'GCS not available'}), 503
    try:
        article = request.json.get('article')
        if not article or not article.get('url'):
            return jsonify({'success': False, 'error': 'Article with URL required'}), 400

        bucket = gcs_client.bucket(GCS_BUCKET_NAME)
        blob = bucket.blob(SAVED_ARTICLES_BLOB)

        articles = []
        generation = 0
        if blob.exists():
            blob.reload()
            generation = blob.generation
            data = json.loads(blob.download_as_text())
            if isinstance(data, list):
                articles = data
            else:
                articles = data.get('articles', [])

        # Check for duplicate URL
        if any(a.get('url') == article['url'] for a in articles):
            return jsonify({'success': True, 'message': 'Already saved', 'articles': articles})

        # Add with timestamp
        article['dateSaved'] = datetime.now(CHICAGO_TZ).isoformat()
        articles.insert(0, article)

        blob.upload_from_string(
            json.dumps({'articles': articles}),
            content_type='application/json',
            if_generation_match=generation
        )
        return jsonify({'success': True, 'articles': articles})

    except Exception as e:
        safe_print(f"[SAVED ARTICLES] Error saving: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/saved-articles', methods=['DELETE'])
def delete_saved_article():
    """Remove an article from saved articles by URL"""
    if not gcs_client:
        return jsonify({'success': False, 'error': 'GCS not available'}), 503
    try:
        url = request.json.get('url')
        if not url:
            return jsonify({'success': False, 'error': 'URL required'}), 400

        bucket = gcs_client.bucket(GCS_BUCKET_NAME)
        blob = bucket.blob(SAVED_ARTICLES_BLOB)

        articles = []
        generation = 0
        if blob.exists():
            blob.reload()
            generation = blob.generation
            data = json.loads(blob.download_as_text())
            if isinstance(data, list):
                articles = data
            else:
                articles = data.get('articles', [])

        articles = [a for a in articles if a.get('url') != url]
        blob.upload_from_string(
            json.dumps({'articles': articles}),
            content_type='application/json',
            if_generation_match=generation
        )
        return jsonify({'success': True, 'articles': articles})

    except Exception as e:
        safe_print(f"[SAVED ARTICLES] Error deleting: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/track-selection', methods=['POST'])
def track_selection():
    """Track article selection for learning/analysis"""
    if not gcs_client:
        return jsonify({'success': False, 'error': 'GCS not configured'}), 500

    try:
        data = request.json
        selection = {
            'timestamp': datetime.now(CHICAGO_TZ).isoformat(),
            'app': 'agent',
            'section': data.get('section'),
            'article': {
                'url': data.get('url'),
                'title': data.get('title'),
                'headline': data.get('headline'),
                'publisher': data.get('publisher'),
                'snippet': data.get('snippet'),
                'impact': data.get('impact')
            },
            'searchQuery': data.get('searchQuery'),
            'searchSource': data.get('searchSource'),
            'timeFilter': data.get('timeFilter'),
            'user': data.get('user', 'unknown'),
            'month': data.get('month'),
            'deselected': data.get('deselected', False)
        }

        year_month = datetime.now(CHICAGO_TZ).strftime('%Y-%m')
        blob_name = f'selection-history/agent/{year_month}.jsonl'

        bucket = gcs_client.bucket(GCS_BUCKET_NAME)
        blob = bucket.blob(blob_name)

        existing = ''
        generation = 0
        if blob.exists():
            blob.reload()
            generation = blob.generation
            existing = blob.download_as_text()

        new_content = existing + json.dumps(selection) + '\n'
        blob.upload_from_string(
            new_content,
            content_type='application/jsonl',
            if_generation_match=generation
        )

        return jsonify({'success': True})
    except Exception as e:
        safe_print(f"[TRACK] Error: {str(e)}")
        return jsonify({'success': True})


# ============================================================================
# MAIN
# ============================================================================

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    print(f"\n=== BriteCo Brief API Server ===")
    print(f"Starting on port {port}")
    app.run(host='0.0.0.0', port=port, debug=True)
