"""
BriteCo Brief - Agent Newsletter Generator
Backend API Server - Adapted from Venue Voice structure
"""

import os
import sys
import json
import re
import requests
import smtplib
import base64
from io import BytesIO
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from dotenv import load_dotenv

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
# ROUTES - ARTICLE SEARCH
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
    """Search for interesting/curious claims stories"""
    try:
        data = request.json
        month = data.get('month', 'january')
        exclude_urls = data.get('exclude_urls', [])

        print(f"\n[API] Searching for curious claims stories (month: {month})...")

        # Build search query for unusual claims
        search_query = f"unusual insurance claims interesting stories P&C property casualty site:claimsjournal.com OR site:insurancejournal.com OR site:propertycasualty360.com"

        try:
            search_results = openai_client.search_web(
                query=search_query,
                exclude_urls=exclude_urls,
                max_results=10
            )

            for result in search_results:
                result['source_url'] = result.get('url', '')

            claims = search_results[:10]

            if len(claims) > 0:
                print(f"[API] Found {len(claims)} claims stories")
                return jsonify({
                    'success': True,
                    'claims': claims,
                    'source': 'openai_responses_api',
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
        spotlight_topic = data.get('spotlight_topic')
        agent_tips_topics = data.get('agent_tips_topics', [])  # List of 5 tips

        print(f"\n[API] Researching selected articles...")

        research_results = {}

        # Research Curious Claims (~200 words)
        if curious_claims_topic:
            safe_print(f"  - Researching Curious Claims: {curious_claims_topic.get('title', 'Unknown')}")
            claims_prompt = f"""You are a senior insurance industry analyst. Research this claims story and produce a briefing (~200 words).

Article: {curious_claims_topic.get('title', 'Unknown')}
Source: {curious_claims_topic.get('url', 'N/A')}
Initial Summary: {curious_claims_topic.get('description', '')}

Produce a structured briefing:

1. THE CLAIM
What happened? Describe the unusual or interesting claim in 2-3 sentences.

2. THE OUTCOME
How was it resolved? What was the insurance company's response?

3. AGENT TAKEAWAY
What can insurance agents learn from this? How does it relate to client conversations?

Target: 150-200 words. Be engaging and informative."""

            claims_research = openai_client.generate_content(
                prompt=claims_prompt,
                model="gpt-4o",
                temperature=0.3,
                max_tokens=500
            )
            research_results['curious_claims'] = claims_research['content']
            print(f"    Curious Claims research: {len(claims_research['content'].split())} words")

        # Research News Roundup (5 bullet points, ~25 words each)
        if roundup_topics and len(roundup_topics) > 0:
            safe_print(f"  - Researching {len(roundup_topics)} roundup articles...")
            roundup_items = []
            for topic in roundup_topics[:5]:
                safe_print(f"    - {topic.get('title', 'Unknown')[:50]}...")
                roundup_prompt = f"""Summarize this insurance news in ONE bullet point (~25 words):

Article: {topic.get('title', 'Unknown')}
Summary: {topic.get('description', '')}
URL: {topic.get('url', 'N/A')}

Output format: [Summary text] - [Source Name]
Example: State Farm announces 15% rate increase in California amid wildfire concerns - Insurance Journal"""

                roundup_result = openai_client.generate_content(
                    prompt=roundup_prompt,
                    model="gpt-4o",
                    temperature=0.2,
                    max_tokens=100
                )
                roundup_items.append({
                    'summary': roundup_result['content'].strip(),
                    'url': topic.get('url', ''),
                    'source': topic.get('publisher', '')
                })
            research_results['roundup'] = roundup_items
            print(f"    Roundup research complete: {len(roundup_items)} items")

        # Research InsurNews Spotlight (~300 words)
        if spotlight_topic:
            safe_print(f"  - Researching Spotlight: {spotlight_topic.get('title', 'Unknown')}")
            spotlight_prompt = f"""You are a senior insurance industry analyst. Produce a detailed briefing (~300 words) on this major news story.

Article: {spotlight_topic.get('title', 'Unknown')}
Source: {spotlight_topic.get('url', 'N/A')}
Initial Summary: {spotlight_topic.get('description', '')}

Produce a structured briefing:

1. EXECUTIVE SUMMARY
2-3 sentences capturing the core news and significance.

2. KEY FACTS & DATA
Bullet points with specific statistics, dates, and facts.

3. INDUSTRY IMPACT
1 paragraph on broader P&C insurance industry implications.

4. WHAT IT MEANS FOR AGENTS
1 paragraph on how this affects independent insurance agents and their clients.

5. ACTIONABLE INSIGHTS
2-3 bullets on what agents should do or consider.

Target: 250-300 words. Be factual and cite specifics."""

            spotlight_research = openai_client.generate_content(
                prompt=spotlight_prompt,
                model="gpt-4o",
                temperature=0.3,
                max_tokens=800
            )
            research_results['spotlight'] = spotlight_research['content']
            print(f"    Spotlight research: {len(spotlight_research['content'].split())} words")

        # Research Agent Advantage Tips (5 tips, ~30 words each)
        if agent_tips_topics and len(agent_tips_topics) > 0:
            safe_print(f"  - Researching {len(agent_tips_topics)} agent tips...")
            tips_items = []
            for topic in agent_tips_topics[:5]:
                safe_print(f"    - {topic.get('title', 'Unknown')[:50]}...")
                tip_prompt = f"""Create ONE actionable tip for insurance agents (~30 words) based on:

Article: {topic.get('title', 'Unknown')}
Summary: {topic.get('description', '')}

Output format: [Tip title]: [Actionable advice]
Example: Follow Up Fast: Respond to leads within 5 minutes to increase conversion rates by up to 400%."""

                tip_result = openai_client.generate_content(
                    prompt=tip_prompt,
                    model="gpt-4o",
                    temperature=0.3,
                    max_tokens=100
                )
                tips_items.append({
                    'tip': tip_result['content'].strip(),
                    'source_url': topic.get('url', '')
                })
            research_results['agent_tips'] = tips_items
            print(f"    Agent tips research complete: {len(tips_items)} items")

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

        if not research:
            return jsonify({'success': False, 'error': 'Research data required'}), 400

        print(f"\n[API] Generating content for {month} using Claude Opus 4.5...")

        if not claude_client:
            raise ValueError("Claude client not available for writing")

        sections = {}
        style_guide = get_style_guide_for_prompt()

        # Generate Introduction (1-4 sentences, ~75 words)
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

        # Generate InsurNews Spotlight from research
        if research.get('spotlight'):
            print("  - Writing InsurNews Spotlight section...")
            spotlight_prompt = f"""You are the copywriter for BriteCo Brief newsletter.

## RESEARCH BRIEFING
{research['spotlight']}

Write the "InsurNews Spotlight" section based on this research.

Requirements:
- 3-4 paragraphs
- Maximum 300 words
- Analytical, insightful tone
- Include specific data points
- End with actionable insights for agents

{style_guide}

Output ONLY the section text, no title or labels."""

            spotlight_result = claude_client.generate_content(
                prompt=spotlight_prompt,
                model="claude-opus-4-5-20251101",
                temperature=0.4,
                max_tokens=600
            )
            sections['spotlight'] = spotlight_result['content'].strip()

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

            prompt_result = openai_client.generate_content(
                prompt=prompt_request,
                model="gpt-4o",
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
# ROUTES - BRAND CHECK
# ============================================================================

@app.route('/api/brand-check', methods=['POST'])
def brand_check():
    """Check newsletter content against brand guidelines"""
    try:
        data = request.json
        content = data.get('content', {})
        html = data.get('html', '')

        print(f"\n[API] Running brand check...")

        # Combine all text content for checking
        all_text = json.dumps(content) if content else html

        check_prompt = f"""You are a brand compliance reviewer for BriteCo Brief, an insurance agent newsletter.

Review this content against brand guidelines:

CONTENT:
{all_text[:3000]}

BRAND GUIDELINES:
- Tone: Professional, knowledgeable, supportive
- Focus: P&C insurance only (property, casualty, auto, homeowners, commercial)
- Avoid: Health insurance, life insurance, political content, international news, jargon overload

CHECK FOR:
1. Any health or life insurance mentions (FAIL if found)
2. Any political content (FAIL if found)
3. Tone consistency (professional but approachable)
4. Clarity and readability
5. Actionable content for agents

OUTPUT FORMAT:
PASS/FAIL: [PASS or FAIL]
SCORE: [1-10]
ISSUES: [List any issues found, or "None"]
SUGGESTIONS: [Any improvement suggestions]"""

        check_result = claude_client.generate_content(
            prompt=check_prompt,
            model="claude-opus-4-5-20251101",
            temperature=0.2,
            max_tokens=500
        )

        result_text = check_result['content'].strip()

        # Parse the result
        passed = 'PASS' in result_text.upper() and 'FAIL' not in result_text.split('PASS')[0].upper()

        print(f"[API] Brand check complete: {'PASS' if passed else 'FAIL'}")

        return jsonify({
            'success': True,
            'passed': passed,
            'details': result_text,
            'generated_at': datetime.now().isoformat()
        })

    except Exception as e:
        print(f"[API ERROR] Brand check failed: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

# ============================================================================
# ROUTES - EXPORT & SHARING
# ============================================================================

@app.route('/api/send-preview', methods=['POST'])
def send_preview():
    """Send newsletter preview to team members via SMTP email"""
    try:
        data = request.json
        recipients = data.get('recipients', [])
        subject = data.get('subject', 'BriteCo Brief Preview')
        html_content = data.get('html', '')

        if not recipients or not html_content:
            return jsonify({"success": False, "error": "Recipients and HTML content required"}), 400

        safe_print(f"[API] Sending preview to {len(recipients)} recipients...")

        # Get SMTP configuration
        smtp_server = os.environ.get('SMTP_SERVER', 'smtp.gmail.com')
        smtp_port = int(os.environ.get('SMTP_PORT', 587))
        smtp_user = os.environ.get('SMTP_USER')
        smtp_password = os.environ.get('SMTP_PASSWORD')

        if not smtp_user or not smtp_password:
            return jsonify({
                "success": False,
                "error": "SMTP credentials not configured. Add SMTP_USER and SMTP_PASSWORD environment variables."
            }), 500

        # Send email to each recipient
        sent_count = 0
        errors = []

        for recipient in recipients:
            try:
                msg = MIMEMultipart('alternative')
                msg['Subject'] = subject
                msg['From'] = smtp_user
                msg['To'] = recipient

                html_part = MIMEText(html_content, 'html')
                msg.attach(html_part)

                with smtplib.SMTP(smtp_server, smtp_port) as server:
                    server.starttls()
                    server.login(smtp_user, smtp_password)
                    server.sendmail(smtp_user, recipient, msg.as_string())

                sent_count += 1
                safe_print(f"[API] Email sent to: {recipient}")

            except Exception as email_error:
                error_msg = f"Failed to send to {recipient}: {str(email_error)}"
                safe_print(f"[API] {error_msg}")
                errors.append(error_msg)

        if sent_count == len(recipients):
            return jsonify({
                "success": True,
                "message": f"Preview sent to {sent_count} recipient(s)",
                "recipients": recipients,
                "from": smtp_user
            })
        elif sent_count > 0:
            return jsonify({
                "success": True,
                "message": f"Preview sent to {sent_count} of {len(recipients)} recipient(s)",
                "recipients": recipients[:sent_count],
                "errors": errors,
                "from": smtp_user
            })
        else:
            return jsonify({
                "success": False,
                "error": "Failed to send to any recipients",
                "details": errors
            }), 500

    except Exception as e:
        safe_print(f"[API] Send preview error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/export-to-docs', methods=['POST'])
def export_to_docs():
    """Export newsletter content to Google Docs"""
    try:
        data = request.json
        content = data.get('content', {})
        title = data.get('title', f"BriteCo Brief - {datetime.now().strftime('%Y-%m-%d')}")

        safe_print(f"[API] Exporting to Google Docs: {title}")

        creds_json = os.environ.get('GOOGLE_DOCS_CREDENTIALS')

        if not creds_json:
            return jsonify({
                "success": False,
                "error": "Google Docs credentials not configured"
            }), 500

        # TODO: Implement actual Google Docs export
        # For now, return placeholder
        return jsonify({
            "success": True,
            "message": "Google Docs export ready",
            "note": "Full implementation coming soon"
        })

    except Exception as e:
        safe_print(f"[API] Export error: {e}")
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

        # Send to Ontraport objects
        result = ontraport_client.create_email(
            subject=subject,
            html_content=html_content,
            plain_text=plain_text,
            from_email=ONTRAPORT_CONFIG['from_email'],
            from_name=ONTRAPORT_CONFIG['from_name']
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
