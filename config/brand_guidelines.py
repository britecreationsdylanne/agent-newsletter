"""
BriteCo Brief - Agent Newsletter Configuration
Brand guidelines and newsletter settings for insurance agents
"""

# Insurance news sources for search queries
INSURANCE_NEWS_SOURCES = [
    "insurancenewsnet.com",
    "insurancejournal.com",
    "propertycasualty360.com",
    "claimsjournal.com",
    "carriermanagement.com",
    "thinkadvisor.com",
    "dig-in.com"
]

# Content filters - what to include/exclude
CONTENT_FILTERS = {
    "include": [
        "property and casualty",
        "P&C",
        "homeowners insurance",
        "auto insurance",
        "commercial insurance",
        "workers compensation",
        "liability insurance",
        "independent agents",
        "insurance technology",
        "claims management"
    ],
    "exclude": [
        "health insurance",
        "life insurance",
        "medicare",
        "medicaid",
        "ACA",
        "affordable care act",
        "political",
        "election",
        "international news",
        # Promotion/personnel news exclusions
        "promoted to",
        "announces promotion",
        "new CEO",
        "new president",
        "executive appointment",
        "joins as",
        "named to",
        "leadership change",
        "personnel announcement",
        "new hire",
        "appointed as",
        "steps down",
        "retires from"
    ]
}

# Ontraport configuration
ONTRAPORT_CONFIG = {
    "objects": ["10004", "10007"],
    "from_email": "agent@brite.co",
    "from_name": "BriteCo Brief"
}

# Team members for preview emails
TEAM_MEMBERS = [
    {"name": "John Ortbal", "email": "john.ortbal@brite.co"},
    {"name": "Stef Lynn", "email": "stef.lynn@brite.co"},
    {"name": "Selena Fragassi", "email": "selena.fragassi@brite.co"}
]

# Brand voice for AI content generation
BRAND_VOICE = {
    "tone": "Professional but approachable, knowledgeable, supportive",
    "style": "Clear, concise, actionable",
    "perspective": "We help independent insurance agents succeed",
    "avoid": [
        "Overly salesy language",
        "Jargon without explanation",
        "Health or life insurance content",
        "Political content",
        "Competitor bashing"
    ]
}

# Newsletter section guidelines with character limits
NEWSLETTER_GUIDELINES = {
    "sections": {
        "introduction": {
            "structure": ["1-4 sentences welcoming readers", "Reference the month/season", "Hint at content inside"],
            "max_words": 75,
            "tone": "Warm, welcoming, brief"
        },
        "brite_spot": {
            "structure": ["BriteCo company news or feature highlight", "New tools or updates for agents"],
            "max_words": 100,
            "tone": "Exciting, informative"
        },
        "curious_claims": {
            "structure": ["The Claim: What happened (2-3 sentences)", "The Outcome: How it was resolved", "Agent Takeaway: Lesson for agents"],
            "max_words": 200,
            "tone": "Engaging, storytelling, educational"
        },
        "news_roundup": {
            "structure": ["5 bullet points", "Each ~25 words", "Include source attribution"],
            "bullets": 5,
            "words_per_bullet": 25,
            "tone": "Factual, concise, newsworthy"
        },
        "insurnews_spotlight": {
            "structure": ["Executive Summary (2-3 sentences)", "Key Facts & Data (bullets)", "Industry Impact (1 paragraph)", "What It Means for Agents (1 paragraph)", "Actionable Insights (2-3 bullets)"],
            "max_words": 300,
            "tone": "Analytical, insightful, practical"
        },
        "agent_advantage": {
            "structure": ["5 actionable tips for agents", "Each ~30 words", "Focus on sales, retention, operations"],
            "tips": 5,
            "words_per_tip": 30,
            "tone": "Helpful, actionable, expert advice"
        }
    },
    "formatting": {
        "headlines": "Title Case",
        "body": "Sentence case",
        "sections": "Bold section headers"
    }
}

# BriteCo brand terminology rules
BRITECO_BRAND = {
    "do": [
        "Call BriteCo an 'insurtech company' or 'insurance provider'",
        "Refer to BriteCo as a 'specialty jewelry insurance provider' when comparing to general insurers",
        "Say 'backed by an AM Best A+ rated Insurance Carrier'",
        "Refer to website as brite.co or https://brite.co"
    ],
    "dont": [
        "Call BriteCo an 'insurance company'",
        "Refer to BriteCo as 'specialized jewelry insurance'",
        "Slander competitors",
        "Say 'we have AM Best policies' or 'we are AM Best'",
        "Refer to website as www.brite.co"
    ]
}


def get_style_guide_for_prompt(section_type=None):
    """
    Generate a prompt-friendly style guide string for AI content generation.

    Args:
        section_type: Optional - section name to include specific guidelines

    Returns:
        Formatted string ready to include in AI prompts
    """
    guide = "## EDITORIAL STYLE GUIDE\n\n"

    # Brand Voice
    guide += "### TONE & VOICE\n"
    guide += f"- Tone: {BRAND_VOICE['tone']}\n"
    guide += f"- Style: {BRAND_VOICE['style']}\n"
    guide += f"- Perspective: {BRAND_VOICE['perspective']}\n"
    guide += "- AVOID: " + ", ".join(BRAND_VOICE['avoid']) + "\n\n"

    # Content Focus
    guide += "### CONTENT FOCUS\n"
    guide += "- INCLUDE topics about: " + ", ".join(CONTENT_FILTERS['include'][:5]) + "\n"
    guide += "- EXCLUDE any content about: " + ", ".join(CONTENT_FILTERS['exclude'][:5]) + "\n\n"

    # BriteCo Brand Rules
    guide += "### BRITECO BRAND TERMINOLOGY\n"
    guide += "DO:\n"
    for rule in BRITECO_BRAND['do'][:3]:
        guide += f"  - {rule}\n"
    guide += "DON'T:\n"
    for rule in BRITECO_BRAND['dont'][:3]:
        guide += f"  - {rule}\n"
    guide += "\n"

    # Section-specific guidelines if requested
    if section_type and section_type in NEWSLETTER_GUIDELINES['sections']:
        section = NEWSLETTER_GUIDELINES['sections'][section_type]
        guide += f"### {section_type.upper()} SECTION REQUIREMENTS\n"
        for item in section.get('structure', []):
            guide += f"- {item}\n"
        if 'max_words' in section:
            guide += f"- Maximum: {section['max_words']} words\n"
        guide += f"- Tone: {section.get('tone', 'Professional')}\n"

    return guide


def get_search_sources_prompt():
    """
    Generate a search sources instruction for web search queries.

    Returns:
        String with preferred sources for insurance news
    """
    sources = " OR ".join([f"site:{s}" for s in INSURANCE_NEWS_SOURCES])
    return f"""
PREFERRED SOURCES:
Search these insurance industry publications: {sources}

CONTENT REQUIREMENTS:
- Focus on Property & Casualty (P&C) insurance only
- Exclude health insurance, life insurance, Medicare/Medicaid content
- Exclude political news and international news
- Include news relevant to independent insurance agents
"""


def get_section_structure(section_type):
    """
    Get the structure requirements for a specific newsletter section.

    Args:
        section_type: Section name (e.g., 'curious_claims', 'news_roundup')

    Returns:
        Dict with structure and tone info, or None if not found
    """
    if section_type in NEWSLETTER_GUIDELINES['sections']:
        return NEWSLETTER_GUIDELINES['sections'][section_type]
    return None
