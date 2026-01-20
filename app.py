"""
BriteCo Brief - Agent Newsletter Generator
Backend API Server
"""

import os
import re
import json
import base64
import smtplib
from io import BytesIO
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from functools import wraps

from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

app = Flask(__name__, static_folder='.', static_url_path='')
CORS(app)

# ============================================================================
# CONFIGURATION
# ============================================================================

# Team members for sending previews
TEAM_MEMBERS = [
    {"name": "John Ortbal", "email": "john.ortbal@brite.co"},
    {"name": "Stef Lynn", "email": "stef.lynn@brite.co"},
    {"name": "Selena Fragassi", "email": "selena.fragassi@brite.co"}
]

# Insurance news sources for agent newsletters
AGENT_NEWS_SOURCES = [
    "insurancenewsnet.com",
    "insurancejournal.com",
    "businessinsurance.com",
    "insurancebusinessmag.com/us",
    "claimsjournal.com",
    "forbes.com/advisor/insurance",
    "propertycasualty360.com"
]

# Content filters for agent newsletters
AGENT_CONTENT_FILTERS = {
    "include": ["property", "casualty", "P&C", "homeowners", "auto", "commercial", "claims", "agents", "brokers"],
    "exclude": ["health insurance", "life insurance", "political", "international", "people news", "obituary", "appointment"]
}

# Ontraport objects for agents
ONTRAPORT_OBJECTS = ["10004", "10007"]
ONTRAPORT_FROM_EMAIL = "agent@brite.co"

# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def safe_print(msg):
    """Thread-safe print with timestamp"""
    timestamp = datetime.now().strftime("%H:%M:%S")
    print(f"[{timestamp}] {msg}", flush=True)

def get_api_client(client_type):
    """Get API client based on type"""
    if client_type == "openai":
        import openai
        return openai.OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
    elif client_type == "anthropic":
        import anthropic
        return anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
    elif client_type == "gemini":
        from google import genai
        return genai.Client(api_key=os.environ.get("GOOGLE_AI_API_KEY"))
    elif client_type == "perplexity":
        import openai
        return openai.OpenAI(
            api_key=os.environ.get("PERPLEXITY_API_KEY"),
            base_url="https://api.perplexity.ai"
        )
    return None

# ============================================================================
# ROUTES - STATIC FILES
# ============================================================================

@app.route('/')
def serve_index():
    return send_from_directory('.', 'index.html')

@app.route('/health')
def health_check():
    return jsonify({"status": "healthy", "service": "briteco-brief"})

# ============================================================================
# ROUTES - TEAM MANAGEMENT
# ============================================================================

@app.route('/api/team-members', methods=['GET'])
def get_team_members():
    """Get list of team members for sending previews"""
    return jsonify({"success": True, "team_members": TEAM_MEMBERS})

# ============================================================================
# ROUTES - RESEARCH & TOPIC DISCOVERY
# ============================================================================

@app.route('/api/research-topics', methods=['POST'])
def research_topics():
    """
    Scan insurance news sources for trending P&C topics.
    Returns 5-8 topic suggestions with brief descriptions.
    """
    try:
        safe_print("[API] Starting topic research...")

        perplexity = get_api_client("perplexity")
        if not perplexity:
            return jsonify({"success": False, "error": "Perplexity API not configured"}), 500

        # Build search query
        sources_list = ", ".join(AGENT_NEWS_SOURCES)

        prompt = f"""Search the following insurance news sources for the most relevant and trending stories from the past 2 weeks:
{sources_list}

Focus ONLY on:
- Property & Casualty (P&C) insurance topics
- Homeowners insurance
- Auto insurance
- Commercial insurance
- Claims trends
- Agent/broker business topics
- Industry regulations affecting P&C

EXCLUDE completely:
- Health insurance
- Life insurance
- Political topics or partisan content
- International news (US only)
- People news (appointments, obituaries)
- Press releases

Return 6-8 distinct topic ideas as a JSON array with this format:
[
  {{
    "topic": "Brief topic title (5-10 words)",
    "description": "2-3 sentence summary of the news angle",
    "relevance": "Why this matters for insurance agents",
    "sources_hint": ["Source1", "Source2"]
  }}
]

Return ONLY the JSON array, no other text."""

        response = perplexity.chat.completions.create(
            model="sonar-pro",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3
        )

        content = response.choices[0].message.content.strip()

        # Parse JSON from response
        if content.startswith("```"):
            content = re.sub(r"^```[a-zA-Z]*\n", "", content)
            content = re.sub(r"\n```$", "", content).strip()

        topics = json.loads(content)

        safe_print(f"[API] Found {len(topics)} topics")
        return jsonify({"success": True, "topics": topics})

    except Exception as e:
        safe_print(f"[API] Topic research error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/research-articles', methods=['POST'])
def research_articles():
    """
    Deep dive research on a selected topic.
    Returns 4-6 articles from different sources with full details.
    """
    try:
        data = request.json
        topic = data.get('topic', '')

        if not topic:
            return jsonify({"success": False, "error": "Topic is required"}), 400

        safe_print(f"[API] Researching articles for: {topic}")

        perplexity = get_api_client("perplexity")
        if not perplexity:
            return jsonify({"success": False, "error": "Perplexity API not configured"}), 500

        sources_list = ", ".join(AGENT_NEWS_SOURCES)

        prompt = f"""Research this insurance topic in depth: "{topic}"

Search these sources: {sources_list}

Find 4-6 recent articles (within past 30 days) that cover different angles of this topic.

For each article, provide:
- The exact article title
- The source website name
- The URL (must be a real, working URL)
- A 2-3 sentence summary of the article's key points
- Key statistics or quotes if available

Return as JSON array:
[
  {{
    "title": "Exact article headline",
    "source": "Source name (e.g., Insurance Journal)",
    "url": "https://full-url-to-article",
    "summary": "2-3 sentence summary",
    "key_points": ["Point 1", "Point 2"],
    "date": "Publication date if available"
  }}
]

IMPORTANT: Only include real articles with working URLs. Return ONLY the JSON array."""

        response = perplexity.chat.completions.create(
            model="sonar-pro",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2
        )

        content = response.choices[0].message.content.strip()

        if content.startswith("```"):
            content = re.sub(r"^```[a-zA-Z]*\n", "", content)
            content = re.sub(r"\n```$", "", content).strip()

        articles = json.loads(content)

        safe_print(f"[API] Found {len(articles)} articles")
        return jsonify({"success": True, "articles": articles})

    except Exception as e:
        safe_print(f"[API] Article research error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/research-claims', methods=['POST'])
def research_claims():
    """
    Search for interesting/unusual claims stories for Curious Claims section.
    """
    try:
        safe_print("[API] Searching for curious claims stories...")

        perplexity = get_api_client("perplexity")
        if not perplexity:
            return jsonify({"success": False, "error": "Perplexity API not configured"}), 500

        prompt = """Search for unusual, interesting, or outrageous insurance claims stories from recent news.

Look for stories that are:
- Quirky or unexpected claims
- Large or notable settlements
- Unusual circumstances
- Interesting legal outcomes
- Stories that would engage insurance professionals

Focus on P&C claims (property, auto, liability) - NOT health or life insurance.
US stories preferred.

Return 5-6 story options as JSON:
[
  {
    "headline": "Catchy headline for the story",
    "summary": "2-3 sentence summary of what happened",
    "source": "News source name",
    "url": "URL to the original story",
    "claim_type": "Type of claim (auto, property, liability, etc.)",
    "interest_factor": "What makes this story interesting"
  }
]

Return ONLY the JSON array."""

        response = perplexity.chat.completions.create(
            model="sonar-pro",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.4
        )

        content = response.choices[0].message.content.strip()

        if content.startswith("```"):
            content = re.sub(r"^```[a-zA-Z]*\n", "", content)
            content = re.sub(r"\n```$", "", content).strip()

        claims = json.loads(content)

        safe_print(f"[API] Found {len(claims)} claims stories")
        return jsonify({"success": True, "claims": claims})

    except Exception as e:
        safe_print(f"[API] Claims research error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/research-roundup', methods=['POST'])
def research_roundup():
    """
    Get quick news items for the Insurance News Roundup section.
    Returns 5 headline-style items with links.
    """
    try:
        safe_print("[API] Gathering news roundup items...")

        perplexity = get_api_client("perplexity")
        if not perplexity:
            return jsonify({"success": False, "error": "Perplexity API not configured"}), 500

        sources_list = ", ".join(AGENT_NEWS_SOURCES)

        prompt = f"""Find 5 recent insurance news headlines that would interest P&C insurance agents.

Search: {sources_list}

Requirements:
- Each should be a single, catchy headline-style sentence
- Include hyperlink to the source
- Mix of topics: market trends, regulations, technology, claims, agent business
- US-focused, P&C only (no health, life, international, political)

Return as JSON:
[
  {{
    "headline": "Catchy one-sentence news item with key detail or statistic",
    "source": "Source name",
    "url": "Full URL to article",
    "category": "market|regulation|technology|claims|business"
  }}
]

Return ONLY 5 items as JSON array."""

        response = perplexity.chat.completions.create(
            model="sonar-pro",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3
        )

        content = response.choices[0].message.content.strip()

        if content.startswith("```"):
            content = re.sub(r"^```[a-zA-Z]*\n", "", content)
            content = re.sub(r"\n```$", "", content).strip()

        items = json.loads(content)

        safe_print(f"[API] Found {len(items)} roundup items")
        return jsonify({"success": True, "items": items})

    except Exception as e:
        safe_print(f"[API] Roundup research error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/research-agent-tips', methods=['POST'])
def research_agent_tips():
    """
    Research content for Agent Advantage section - tips and advice for agents.
    """
    try:
        data = request.json
        topic_hint = data.get('topic', '')

        safe_print(f"[API] Researching agent tips{' for: ' + topic_hint if topic_hint else ''}...")

        perplexity = get_api_client("perplexity")
        if not perplexity:
            return jsonify({"success": False, "error": "Perplexity API not configured"}), 500

        topic_context = f" related to '{topic_hint}'" if topic_hint else ""

        prompt = f"""Find actionable tips and advice for independent insurance agents{topic_context}.

Search for recent articles, guides, or expert advice that help agents:
- Grow their business
- Improve client relationships
- Navigate market challenges
- Use technology effectively
- Handle claims better
- Increase sales/retention

Return 5-6 topic options for an "Agent Advantage" newsletter section:
[
  {{
    "title": "Tip topic title (5-10 words)",
    "angle": "The specific advice angle",
    "key_points": ["Point 1", "Point 2", "Point 3", "Point 4", "Point 5"],
    "source_articles": ["Article title 1", "Article title 2"],
    "relevance": "Why this matters now for agents"
  }}
]

Return ONLY the JSON array."""

        response = perplexity.chat.completions.create(
            model="sonar-pro",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.4
        )

        content = response.choices[0].message.content.strip()

        if content.startswith("```"):
            content = re.sub(r"^```[a-zA-Z]*\n", "", content)
            content = re.sub(r"\n```$", "", content).strip()

        tips = json.loads(content)

        safe_print(f"[API] Found {len(tips)} tip topics")
        return jsonify({"success": True, "tips": tips})

    except Exception as e:
        safe_print(f"[API] Agent tips research error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

# ============================================================================
# ROUTES - CONTENT GENERATION
# ============================================================================

@app.route('/api/generate-intro', methods=['POST'])
def generate_intro():
    """Generate the newsletter introduction section."""
    try:
        data = request.json
        highlights = data.get('highlights', [])
        announcement = data.get('announcement', '')

        safe_print("[API] Generating newsletter introduction...")

        claude = get_api_client("anthropic")
        if not claude:
            return jsonify({"success": False, "error": "Anthropic API not configured"}), 500

        highlights_text = "\n".join([f"- {h}" for h in highlights]) if highlights else "No specific highlights provided"

        prompt = f"""Write a brief newsletter introduction for "The BriteCo Brief" - an insurance agent newsletter.

Newsletter highlights to mention:
{highlights_text}

Special announcement (if any): {announcement if announcement else 'None'}

Requirements:
- 1-4 sentences, punchy and engaging
- Address readers as "Agents"
- Highlight what's in this issue
- Include any special announcements, contests, or calls-to-action
- Professional but friendly tone
- End with enthusiasm for the content

Example style:
"Agents, we have great news to share with you — opportunities to sell BriteCo's new wedding insurance will soon roll out, giving you more chances to earn commissions. Plus, we look at the role of AI in shaping a typical workday and provide tips on how to best prepare your clients as the hurricane and tornado seasons heat up this summer."

Write ONLY the introduction paragraph, no other text."""

        message = claude.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}]
        )

        intro = message.content[0].text.strip()

        safe_print("[API] Introduction generated successfully")
        return jsonify({"success": True, "content": intro})

    except Exception as e:
        safe_print(f"[API] Intro generation error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/generate-brite-spot', methods=['POST'])
def generate_brite_spot():
    """Generate The Brite Spot section content."""
    try:
        data = request.json
        title = data.get('title', '')
        topic = data.get('topic', '')
        details = data.get('details', '')

        if not title or not topic:
            return jsonify({"success": False, "error": "Title and topic are required"}), 400

        safe_print(f"[API] Generating Brite Spot content for: {title}")

        claude = get_api_client("anthropic")
        if not claude:
            return jsonify({"success": False, "error": "Anthropic API not configured"}), 500

        prompt = f"""Write content for "The Brite Spot" section of an insurance agent newsletter.

Title: {title}
Topic/Announcement: {topic}
Additional details: {details if details else 'None provided'}

Requirements:
- Sub-header title: Use the provided title (max 15 words)
- Body: Maximum 100 words
- Announce a new feature, tool, product, or company news
- Professional but engaging tone
- Clear value proposition for agents

Return as JSON:
{{
  "title": "The sub-header title",
  "body": "The main body text (max 100 words)"
}}

Return ONLY the JSON."""

        message = claude.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=400,
            messages=[{"role": "user", "content": prompt}]
        )

        content = message.content[0].text.strip()

        if content.startswith("```"):
            content = re.sub(r"^```[a-zA-Z]*\n", "", content)
            content = re.sub(r"\n```$", "", content).strip()

        result = json.loads(content)

        safe_print("[API] Brite Spot content generated successfully")
        return jsonify({"success": True, "content": result})

    except Exception as e:
        safe_print(f"[API] Brite Spot generation error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/generate-insurnews', methods=['POST'])
def generate_insurnews():
    """Generate InsurNews Spotlight section with multiple sources."""
    try:
        data = request.json
        topic = data.get('topic', '')
        articles = data.get('articles', [])

        if not topic or not articles:
            return jsonify({"success": False, "error": "Topic and articles are required"}), 400

        safe_print(f"[API] Generating InsurNews Spotlight for: {topic}")

        claude = get_api_client("anthropic")
        if not claude:
            return jsonify({"success": False, "error": "Anthropic API not configured"}), 500

        articles_text = "\n\n".join([
            f"Source: {a.get('source', 'Unknown')}\nTitle: {a.get('title', '')}\nURL: {a.get('url', '')}\nSummary: {a.get('summary', '')}"
            for a in articles
        ])

        prompt = f"""Write the "InsurNews Spotlight" section for an insurance agent newsletter.

Main Topic: {topic}

Source Articles:
{articles_text}

Requirements:
- Sub-header: A compelling title (max 15 words) that captures the main story
- Opening paragraph: 1-4 sentences introducing the topic
- Up to 4 H3 subsections, each with:
  - A clear subheading
  - 1-2 paragraphs (1-4 sentences each)
  - Inline hyperlinks to source articles where relevant
- "Implications for Agents" as the final H3
- Total length: 400-600 words

IMPORTANT: Include hyperlinks to the source articles naturally within the text using markdown format [text](url)

Return as JSON:
{{
  "title": "Main sub-header title",
  "intro": "Opening paragraph",
  "sections": [
    {{
      "heading": "H3 heading",
      "content": "Paragraph(s) with [hyperlinks](url) embedded"
    }}
  ],
  "agent_implications": "Final paragraph about what this means for agents"
}}

Return ONLY the JSON."""

        message = claude.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1500,
            messages=[{"role": "user", "content": prompt}]
        )

        content = message.content[0].text.strip()

        if content.startswith("```"):
            content = re.sub(r"^```[a-zA-Z]*\n", "", content)
            content = re.sub(r"\n```$", "", content).strip()

        result = json.loads(content)

        safe_print("[API] InsurNews Spotlight generated successfully")
        return jsonify({"success": True, "content": result})

    except Exception as e:
        safe_print(f"[API] InsurNews generation error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/generate-curious-claims', methods=['POST'])
def generate_curious_claims():
    """Generate Curious Claims section content."""
    try:
        data = request.json
        claim_story = data.get('story', {})

        if not claim_story:
            return jsonify({"success": False, "error": "Claim story data is required"}), 400

        safe_print(f"[API] Generating Curious Claims for: {claim_story.get('headline', 'Unknown')}")

        claude = get_api_client("anthropic")
        if not claude:
            return jsonify({"success": False, "error": "Anthropic API not configured"}), 500

        prompt = f"""Write the "Curious Claims" section for an insurance agent newsletter.

Story Details:
Headline: {claim_story.get('headline', '')}
Summary: {claim_story.get('summary', '')}
Source: {claim_story.get('source', '')}
URL: {claim_story.get('url', '')}
Claim Type: {claim_story.get('claim_type', '')}
Interest Factor: {claim_story.get('interest_factor', '')}

Requirements:
- Sub-header title: Catchy, max 15 words
- At least 2 paragraphs, each 1-4+ sentences
- Can include an optional H3 subheading if it helps structure
- Include hyperlink to source article
- Engaging, slightly playful tone while remaining professional
- End with insurance relevance or takeaway

Return as JSON:
{{
  "title": "Catchy sub-header title",
  "paragraphs": [
    "First paragraph with story setup...",
    "Second paragraph with details and [source link](url)..."
  ],
  "subheading": "Optional H3 if needed (or null)",
  "subheading_content": "Content under subheading (or null)"
}}

Return ONLY the JSON."""

        message = claude.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=800,
            messages=[{"role": "user", "content": prompt}]
        )

        content = message.content[0].text.strip()

        if content.startswith("```"):
            content = re.sub(r"^```[a-zA-Z]*\n", "", content)
            content = re.sub(r"\n```$", "", content).strip()

        result = json.loads(content)

        safe_print("[API] Curious Claims generated successfully")
        return jsonify({"success": True, "content": result})

    except Exception as e:
        safe_print(f"[API] Curious Claims generation error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/generate-agent-advantage', methods=['POST'])
def generate_agent_advantage():
    """Generate Agent Advantage section with 5 tips."""
    try:
        data = request.json
        topic = data.get('topic', {})

        if not topic:
            return jsonify({"success": False, "error": "Topic data is required"}), 400

        safe_print(f"[API] Generating Agent Advantage for: {topic.get('title', 'Unknown')}")

        claude = get_api_client("anthropic")
        if not claude:
            return jsonify({"success": False, "error": "Anthropic API not configured"}), 500

        prompt = f"""Write the "Agent Advantage" section for an insurance agent newsletter.

Topic: {topic.get('title', '')}
Angle: {topic.get('angle', '')}
Key Points to Cover: {json.dumps(topic.get('key_points', []))}
Why It Matters: {topic.get('relevance', '')}

Requirements:
- Sub-header title: Max 15 words, action-oriented
- Quick intro paragraph (2-3 sentences)
- Exactly 5 bullet points, each with:
  - Mini-title (up to 10 words, bold)
  - 1-3 supporting sentences
- Optional closing sentence to wrap up

Return as JSON:
{{
  "title": "Sub-header title",
  "intro": "Brief intro paragraph",
  "tips": [
    {{
      "mini_title": "Bold mini-title",
      "content": "1-3 sentences of supporting content"
    }}
  ],
  "closing": "Optional closing sentence (or null)"
}}

Return ONLY the JSON with exactly 5 tips."""

        message = claude.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1000,
            messages=[{"role": "user", "content": prompt}]
        )

        content = message.content[0].text.strip()

        if content.startswith("```"):
            content = re.sub(r"^```[a-zA-Z]*\n", "", content)
            content = re.sub(r"\n```$", "", content).strip()

        result = json.loads(content)

        safe_print("[API] Agent Advantage generated successfully")
        return jsonify({"success": True, "content": result})

    except Exception as e:
        safe_print(f"[API] Agent Advantage generation error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

# ============================================================================
# ROUTES - IMAGE GENERATION
# ============================================================================

@app.route('/api/generate-image', methods=['POST'])
def generate_image():
    """Generate AI image based on prompt."""
    try:
        data = request.json
        prompt = data.get('prompt', '')
        section = data.get('section', 'general')

        if not prompt:
            return jsonify({"success": False, "error": "Prompt is required"}), 400

        safe_print(f"[API] Generating image for {section}: {prompt[:50]}...")

        gemini = get_api_client("gemini")
        if not gemini:
            return jsonify({"success": False, "error": "Gemini API not configured"}), 500

        # Enhance prompt for better image generation
        enhanced_prompt = f"""Create a professional, modern illustration for an insurance industry newsletter.

Topic: {prompt}

Style requirements:
- Clean, professional corporate style
- Modern flat design or subtle 3D
- Colors: Use teal (#037E7F), coral (#FE8916), and neutral tones
- No text in the image
- Suitable for email newsletter
- Business/insurance industry appropriate"""

        response = gemini.models.generate_images(
            model="imagen-3.0-generate-002",
            prompt=enhanced_prompt,
            config={
                "number_of_images": 1,
                "aspect_ratio": "16:9",
                "safety_filter_level": "BLOCK_MEDIUM_AND_ABOVE"
            }
        )

        if response.generated_images and len(response.generated_images) > 0:
            image_data = response.generated_images[0].image.image_bytes

            # Resize image
            from PIL import Image
            pil_image = Image.open(BytesIO(image_data))

            # Target size based on section
            if section in ['brite_spot', 'curious_claims', 'agent_advantage', 'insurnews']:
                target_width = 203
                target_height = 152
            else:
                target_width = 400
                target_height = 225

            # Resize maintaining aspect ratio and crop to fit
            img_aspect = pil_image.width / pil_image.height
            target_aspect = target_width / target_height

            if img_aspect > target_aspect:
                new_height = target_height
                new_width = int(target_height * img_aspect)
            else:
                new_width = target_width
                new_height = int(target_width / img_aspect)

            resized = pil_image.resize((new_width, new_height), Image.Resampling.LANCZOS)

            # Center crop
            left = (new_width - target_width) // 2
            top = (new_height - target_height) // 2
            cropped = resized.crop((left, top, left + target_width, top + target_height))

            # Convert to base64
            buffer = BytesIO()
            cropped.save(buffer, format='PNG', optimize=True)
            image_base64 = base64.b64encode(buffer.getvalue()).decode('utf-8')

            image_url = f"data:image/png;base64,{image_base64}"

            safe_print(f"[API] Image generated successfully for {section}")
            return jsonify({"success": True, "image_url": image_url})
        else:
            return jsonify({"success": False, "error": "No image generated"}), 500

    except Exception as e:
        safe_print(f"[API] Image generation error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

# ============================================================================
# ROUTES - BRAND CHECK
# ============================================================================

@app.route('/api/brand-check', methods=['POST'])
def brand_check():
    """Run content through brand guidelines check."""
    try:
        data = request.json
        content = data.get('content', {})

        safe_print("[API] Running brand check...")

        claude = get_api_client("anthropic")
        if not claude:
            return jsonify({"success": False, "error": "Anthropic API not configured"}), 500

        content_text = json.dumps(content, indent=2)

        prompt = f"""Review this insurance newsletter content for brand consistency and quality.

Content to review:
{content_text}

Check for:
1. Professional tone appropriate for insurance agents
2. Accuracy and clarity of information
3. Consistent formatting
4. Appropriate length for each section
5. Engaging but not sensational language
6. Proper attribution of sources
7. No health/life insurance, political, or international content
8. Clear calls-to-action where appropriate

Return as JSON:
{{
  "overall_score": 1-10,
  "passes": true/false,
  "issues": [
    {{
      "section": "Section name",
      "issue": "Description of issue",
      "suggestion": "How to fix"
    }}
  ],
  "strengths": ["Strength 1", "Strength 2"],
  "suggestions": ["General suggestion 1", "General suggestion 2"]
}}

Return ONLY the JSON."""

        message = claude.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1000,
            messages=[{"role": "user", "content": prompt}]
        )

        result_text = message.content[0].text.strip()

        if result_text.startswith("```"):
            result_text = re.sub(r"^```[a-zA-Z]*\n", "", result_text)
            result_text = re.sub(r"\n```$", "", result_text).strip()

        result = json.loads(result_text)

        safe_print(f"[API] Brand check complete - Score: {result.get('overall_score', 'N/A')}")
        return jsonify({"success": True, "result": result})

    except Exception as e:
        safe_print(f"[API] Brand check error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

# ============================================================================
# ROUTES - EXPORT & SHARING
# ============================================================================

@app.route('/api/send-preview', methods=['POST'])
def send_preview():
    """Send newsletter preview to team members via email."""
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

                # Attach HTML content
                html_part = MIMEText(html_content, 'html')
                msg.attach(html_part)

                # Connect and send
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
    """Export newsletter content to Google Docs."""
    try:
        data = request.json
        content = data.get('content', {})
        title = data.get('title', f"BriteCo Brief - {datetime.now().strftime('%Y-%m-%d')}")

        safe_print(f"[API] Exporting to Google Docs: {title}")

        # Check for Google Docs credentials
        creds_json = os.environ.get('GOOGLE_DOCS_CREDENTIALS')

        if not creds_json:
            return jsonify({
                "success": False,
                "error": "Google Docs credentials not configured",
                "setup_instructions": "Add GOOGLE_DOCS_CREDENTIALS environment variable with service account JSON"
            }), 500

        # Placeholder - actual Google Docs integration would go here
        # This requires google-api-python-client and proper authentication

        return jsonify({
            "success": True,
            "message": "Google Docs export ready",
            "title": title,
            "note": "Full integration requires Google Docs API setup"
        })

    except Exception as e:
        safe_print(f"[API] Google Docs export error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/download-html', methods=['POST'])
def download_html():
    """Generate downloadable HTML file content."""
    try:
        data = request.json
        html_content = data.get('html', '')

        if not html_content:
            return jsonify({"success": False, "error": "HTML content required"}), 400

        # Return the HTML content for client-side download
        return jsonify({
            "success": True,
            "html": html_content,
            "filename": f"briteco-brief-{datetime.now().strftime('%Y%m%d')}.html"
        })

    except Exception as e:
        safe_print(f"[API] Download HTML error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

# ============================================================================
# ROUTES - ONTRAPORT INTEGRATION
# ============================================================================

@app.route('/api/send-to-ontraport', methods=['POST'])
def send_to_ontraport():
    """Send newsletter to Ontraport for distribution."""
    try:
        data = request.json
        html_content = data.get('html', '')
        subject = data.get('subject', '')
        preheader = data.get('preheader', '')

        if not html_content or not subject:
            return jsonify({"success": False, "error": "HTML content and subject required"}), 400

        safe_print("[API] Preparing to send to Ontraport...")

        app_id = os.environ.get('ONTRAPORT_APP_ID')
        api_key = os.environ.get('ONTRAPORT_API_KEY')

        if not app_id or not api_key:
            return jsonify({"success": False, "error": "Ontraport credentials not configured"}), 500

        # Ontraport API integration would go here
        # Objects: 10004 and 10007
        # From: agent@brite.co

        return jsonify({
            "success": True,
            "message": "Newsletter ready for Ontraport",
            "objects": ONTRAPORT_OBJECTS,
            "from_email": ONTRAPORT_FROM_EMAIL,
            "subject": subject
        })

    except Exception as e:
        safe_print(f"[API] Ontraport error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

# ============================================================================
# MAIN
# ============================================================================

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    safe_print(f"Starting BriteCo Brief server on port {port}")
    app.run(host='0.0.0.0', port=port, debug=True)
