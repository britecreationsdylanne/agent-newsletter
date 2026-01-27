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
    "from_name": "BriteCo Insurance"
}

# Team members for preview emails
TEAM_MEMBERS = [
    {"name": "John Ortbal", "email": "john.ortbal@brite.co"},
    {"name": "Stef Lynn", "email": "stef.lynn@brite.co"},
    {"name": "Selena Fragassi", "email": "selena.fragassi@brite.co"}
]

# Brand voice for AI content generation
BRAND_VOICE = {
    "tone": "Professional but approachable, knowledgeable, supportive, with a dash of wit",
    "style": "Clear, concise, actionable — with clever phrasing and the occasional wry observation",
    "perspective": "We help independent insurance agents succeed",
    "wit_guidelines": [
        "Use light wordplay or clever turns of phrase when it fits naturally",
        "A well-placed quip or dry observation keeps readers engaged",
        "Wit should enhance, never distract from, the information",
        "Think 'smart friend at a conference' not 'stand-up comedian'",
        "One witty line per section is plenty — don't force it"
    ],
    "avoid": [
        "Overly salesy language",
        "Jargon without explanation",
        "Health or life insurance content",
        "Political content",
        "Competitor bashing",
        "Over-the-top puns or forced humor that undermines credibility"
    ]
}

# Writing style guide extracted from 6 months of Agent newsletters (Aug 2025 - Jan 2026)
WRITING_STYLE_GUIDE = {
    "introduction": {
        "patterns": [
            "Start with a seasonal/monthly reference",
            "Use 'we' to create partnership feel",
            "Mention what's inside the newsletter",
            "Keep it warm but brief (2-3 sentences max)"
        ],
        "example_openers": [
            "Happy [Month]! As [seasonal reference], we're here to help you [benefit].",
            "Welcome to [Month]'s edition of the Agent Newsletter!",
            "As we head into [season], here's what's new in the P&C world.",
            "[Month] is here, and we've got the latest updates to keep you informed."
        ],
        "phrases_to_use": [
            "keeping you informed",
            "staying ahead",
            "industry insights",
            "your success"
        ]
    },
    "brite_spot": {
        "patterns": [
            "Lead with the benefit to agents",
            "Mention specific BriteCo features or updates",
            "Include a call-to-action when relevant",
            "Use excitement without being salesy"
        ],
        "example_structures": [
            "[Feature name] is now available! [What it does]. [How agents benefit].",
            "We're excited to announce [update]. This means [benefit for agents].",
            "New this month: [feature]. [Brief explanation]. [How to access/use it]."
        ],
        "phrases_to_use": [
            "streamline your workflow",
            "save you time",
            "help your clients",
            "new tools to help you succeed"
        ]
    },
    "curious_claims": {
        "patterns": [
            "Start with 'The Claim:' - describe the unusual situation in 2-3 sentences",
            "Follow with 'The Outcome:' - explain how it was resolved",
            "End with 'Agent Takeaway:' - practical lesson for agents",
            "Use storytelling to make it memorable"
        ],
        "example_structures": [
            "The Claim: [Unusual situation described vividly]. The Outcome: [Resolution]. Agent Takeaway: [Practical lesson].",
            "What happens when [scenario]? That's exactly what happened to [policyholder type]..."
        ],
        "tone_notes": [
            "Be engaging but factual",
            "Use specific details to paint a picture",
            "Make the takeaway actionable",
            "Avoid sensationalism"
        ]
    },
    "news_roundup": {
        "patterns": [
            "5 bullet points, each ~25-30 words",
            "Start each bullet with a strong action verb or key topic",
            "Include source attribution in parentheses",
            "Focus on P&C-relevant news only",
            "Mix of industry trends, regulatory updates, and market news"
        ],
        "example_bullets": [
            "Homeowners insurance premiums continue to rise as catastrophe losses mount, with average increases of X% nationwide. (Insurance Journal)",
            "The NAIC issued new guidance on [topic], affecting how agents [action]. (PropertyCasualty360)",
            "Auto insurers are adopting AI-powered claims processing, reducing settlement times by X%. (CarrierManagement)"
        ],
        "avoid": [
            "Health/life insurance news",
            "Political commentary",
            "Personnel announcements (new CEO, promotions)",
            "International news unless directly affecting US market"
        ]
    },
    "spotlight": {
        "patterns": [
            "Executive summary: 2-3 sentences capturing the key story",
            "Key facts and data: 3-5 bullet points with statistics",
            "Industry impact: 1 paragraph on broader implications",
            "What it means for agents: 1 paragraph with practical implications",
            "Actionable insights: 2-3 bullet points agents can act on"
        ],
        "example_structure": [
            "## [Headline]\n\n[2-3 sentence summary]\n\n### Key Facts\n- [Stat 1]\n- [Stat 2]\n- [Stat 3]\n\n### Industry Impact\n[Paragraph]\n\n### What This Means for You\n[Paragraph]\n\n### Action Items\n- [Actionable tip 1]\n- [Actionable tip 2]"
        ],
        "tone_notes": [
            "Analytical but accessible",
            "Data-driven with clear sources",
            "Always connect back to agent relevance",
            "Avoid jargon without explanation"
        ]
    },
    "agent_advantage": {
        "patterns": [
            "5 actionable tips, each ~30 words",
            "Start each tip with an action verb",
            "Focus on sales, retention, and operations",
            "Be specific and practical"
        ],
        "example_tips": [
            "Review your clients' home values annually - rising construction costs mean many policies are underinsured. A quick coverage check builds trust and prevents claims gaps.",
            "Leverage social media for client retention: Share seasonal safety tips and industry updates to stay top-of-mind without being salesy.",
            "Cross-sell strategically: When renewing auto policies, mention umbrella coverage - it's an easy add that provides significant protection."
        ],
        "categories": [
            "Client retention strategies",
            "Sales techniques",
            "Operational efficiency",
            "Compliance reminders",
            "Technology adoption"
        ]
    },
    "general_writing_rules": {
        "sentence_structure": [
            "Keep sentences short and punchy (15-20 words average)",
            "Use active voice over passive",
            "Lead with the most important information",
            "One idea per sentence"
        ],
        "formatting": [
            "Use Title Case for headlines",
            "Use sentence case for body text",
            "Bold key terms sparingly",
            "Use bullets for lists of 3+ items"
        ],
        "word_choice": [
            "Use 'you' and 'your' to speak directly to agents",
            "Use 'we' when referring to BriteCo",
            "Avoid jargon or define it when necessary",
            "Prefer concrete over abstract language"
        ],
        "transitions": [
            "Use section headers to guide readers",
            "Connect sections with brief transitions",
            "End sections with forward-looking statements when appropriate"
        ]
    }
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
    guide += "- AVOID: " + ", ".join(BRAND_VOICE['avoid']) + "\n"
    if 'wit_guidelines' in BRAND_VOICE:
        guide += "\n### WIT & PERSONALITY\n"
        for wg in BRAND_VOICE['wit_guidelines']:
            guide += f"- {wg}\n"
    guide += "\n"

    # General Writing Rules
    guide += "### WRITING RULES\n"
    for rule in WRITING_STYLE_GUIDE['general_writing_rules']['sentence_structure'][:3]:
        guide += f"- {rule}\n"
    for rule in WRITING_STYLE_GUIDE['general_writing_rules']['word_choice'][:2]:
        guide += f"- {rule}\n"
    guide += "\n"

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
        guide += f"- Tone: {section.get('tone', 'Professional')}\n\n"

        # Add detailed writing style for this section
        style_key = section_type.replace('insurnews_', '')  # Map section names
        if style_key in WRITING_STYLE_GUIDE:
            style = WRITING_STYLE_GUIDE[style_key]
            guide += f"### {section_type.upper()} WRITING PATTERNS\n"
            for pattern in style.get('patterns', [])[:4]:
                guide += f"- {pattern}\n"
            if 'example_openers' in style:
                guide += "\nExample openers:\n"
                for ex in style['example_openers'][:2]:
                    guide += f'  "{ex}"\n'
            if 'example_bullets' in style:
                guide += "\nExample bullets:\n"
                for ex in style['example_bullets'][:2]:
                    guide += f'  "{ex}"\n'
            if 'example_tips' in style:
                guide += "\nExample tips:\n"
                for ex in style['example_tips'][:2]:
                    guide += f'  "{ex}"\n'
            if 'phrases_to_use' in style:
                guide += f"\nPhrases to incorporate: {', '.join(style['phrases_to_use'][:4])}\n"

    return guide


def get_section_style_examples(section_type):
    """
    Get example content and patterns for a specific section type.

    Args:
        section_type: Section name (e.g., 'introduction', 'curious_claims')

    Returns:
        Dict with examples and patterns, or None if not found
    """
    style_key = section_type.replace('insurnews_', '')
    if style_key in WRITING_STYLE_GUIDE:
        return WRITING_STYLE_GUIDE[style_key]
    return None


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


# ============================================================================
# HUMANIZATION GUIDELINES - Critical for avoiding AI-sounding content
# Extracted from BriteCo-Brief-Style-Guide.md (6 months of newsletters)
# ============================================================================

AI_TELLS_TO_AVOID = {
    "overused_transitions": [
        "Additionally",
        "Furthermore",
        "It's worth noting that",
        "It's important to understand",
        "In today's [industry/world]",
        "Navigating the [X] landscape",
        "At the end of the day",
        "Moving forward",
        "In this regard",
        "Leverage" # as a verb
    ],
    "empty_intensifiers": [
        "Very",
        "Extremely",
        "Incredibly",
        "Highly",
        "Significantly",
        "Robust",
        "Comprehensive",
        "Cutting-edge",
        "Innovative",
        "Seamless",
        "Seamlessly"
    ],
    "hollow_openers": [
        "In the ever-evolving world of...",
        "As we all know...",
        "It goes without saying...",
        "Needless to say...",
        "When it comes to...",
        "In terms of...",
        "The fact of the matter is..."
    ],
    "vague_language": [
        "Many homeowners are affected",  # Say "47% of homeowners"
        "In recent years",  # Say "Since 2023"
        "A significant number of",  # Use actual numbers
        "Various factors contribute to",  # Name the factors
        "This can lead to issues"  # Say what the specific problem is
    ],
    "vocabulary_red_flags": [
        "Landscape" # used metaphorically
        "Navigate" # used metaphorically
        "Robust",
        "Comprehensive",
        "Various",
        "Numerous",
        "Solutions",
        "Empower",
        "Foster",
        "Ensure" # overused
        "Impactful"
    ]
}

HUMAN_WRITING_PATTERNS = {
    "natural_expressions": [
        "It's hard to believe...",
        "Here's what you need to know...",
        "The twist?",
        "Not surprising...",
        "In fact...",
        "That said...",
        "The reality is...",
        "Bottom line:",
        "For one thing...",
        "But will it be covered by insurance?",
        "Spoiler alert:",
        "Plot twist:",
        "You can't make this stuff up.",
        "File this one under...",
        "Let's just say..."
    ],
    "sentence_variety": [
        "Vary sentence length - mix short punchy sentences with longer ones",
        "Use contractions (don't, won't, it's) - real humans use them",
        "Start some sentences with 'And' or 'But' for flow",
        "Use occasional sentence fragments for emphasis",
        "Ask rhetorical questions to engage readers"
    ],
    "specificity_rules": [
        "Use specific names, dates, and places",
        "Cite exact percentages and dollar amounts",
        "Quote real publications by name: 'According to PropertyCasualty360...'",
        "Include telling details that make stories real",
        "Name actual states, companies, and people when possible"
    ]
}

SECTION_TONE_CALIBRATION = {
    "news_roundup": {
        "tone": "Straight, factual — with a sharp headline edge",
        "rules": [
            "No editorializing in the body, but headlines can be cleverly phrased",
            "Let statistics speak",
            "Neutral presentation with crisp language",
            "Start each bullet with bold topic phrase — make it memorable"
        ]
    },
    "curious_claims": {
        "tone": "Lightest touch, playful, witty",
        "rules": [
            "Puns and wordplay welcome in headlines — lean into it here",
            "Storytelling mode with dry humor",
            "Can show amusement at absurd situations",
            "Use vivid, specific details",
            "This is the section where wit shines most — have fun with it"
        ]
    },
    "brite_spot": {
        "tone": "Warm, supportive, lightly clever",
        "rules": [
            "Celebratory without being over-the-top",
            "Clear and direct CTAs",
            "Lead with agent benefit",
            "Use 'we' and 'you' frequently",
            "A witty opening line can hook readers before the CTA"
        ]
    },
    "spotlight": {
        "tone": "Authoritative but accessible, with smart observations",
        "rules": [
            "Show your work with source citations",
            "Can express concern about trends — a wry take is welcome",
            "Always end with practical implications for agents",
            "Use subheadings to break up content",
            "A sharp observation about the data makes it more quotable"
        ]
    },
    "agent_advantage": {
        "tone": "Coach-like, practical, with personality",
        "rules": [
            "Direct advice using 'you should...'",
            "Encouraging without being preachy",
            "Practical, implementable tips",
            "Each tip is actionable immediately",
            "A conversational, slightly irreverent tone keeps agents reading"
        ]
    },
    "introduction": {
        "tone": "Warm, inviting, with a hook",
        "rules": [
            "Open with something unexpected or clever to pull readers in",
            "Use 'we' to create partnership feel",
            "Keep it brief (2-3 sentences)",
            "A light quip about the season or news cycle sets a friendly tone"
        ]
    }
}

# Before/After examples for prompts
HUMANIZATION_EXAMPLES = {
    "news_roundup": {
        "ai_style": "**Insurance industry trends** are showing significant changes in 2026, with various factors contributing to the evolving landscape that agents should be aware of.",
        "human_style": "**Property & Casualty Premiums** Will Rise 7% on Average By the End of 2025, with Much of the Share Tied to Increased Rates for Homes and Autos"
    },
    "intro": {
        "ai_style": "Welcome to this month's edition of The BriteCo Brief. In this issue, we will be exploring various important topics that are relevant to insurance professionals in today's ever-changing market environment.",
        "human_style": "It's hard to believe it's been 20 years since Hurricane Katrina caused one of the biggest catastrophes in US history. We look at how the industry is better prepared today, provide tips on retaining small business customers, and examine the curious world of alien abduction insurance."
    },
    "curious_claims": {
        "ai_style": "In an interesting development in the insurance world, a unique claim has emerged that showcases the diverse nature of insurance cases.",
        "human_style": "A driver in western North Carolina recently got the surprise of her life when she found a surprise guest in her passenger seat. As Melissa Schlarb traversed Route 74 near the Great Smoky Mountains, a dead cat came crashing through her windshield."
    },
    "spotlight": {
        "ai_style": "The current state of homeowners insurance is characterized by various challenges that are impacting consumers and industry professionals alike. Multiple factors are contributing to this situation.",
        "human_style": "The wild swings we saw in homeowners insurance and home market prices in 2025 are not slowing down any time soon. New reports show the drastic measures some property owners are going to—from tapping into home warranties to forgoing homeownership altogether."
    },
    "agent_advantage": {
        "ai_style": "**Maintain Regular Communication.** It is important for agents to maintain regular communication with their clients throughout the policy period. This helps to build relationships.",
        "human_style": "**Schedule Annual Reviews.** Don't wait for renewal time. Proactive mid-year check-ins show clients you're invested in their protection year-round."
    }
}


def get_humanization_guidelines(section_type=None):
    """
    Get humanization guidelines to avoid AI-sounding content.

    Args:
        section_type: Optional section name for section-specific tone

    Returns:
        Formatted string for AI prompts
    """
    guide = "\n## CRITICAL: HUMANIZATION GUIDELINES\n\n"
    guide += "Your writing must sound like it was written by a human, not AI.\n\n"

    # Words/phrases to avoid
    guide += "### NEVER USE THESE (AI Tells):\n"
    guide += "- Transitions: " + ", ".join(AI_TELLS_TO_AVOID['overused_transitions'][:6]) + "\n"
    guide += "- Intensifiers: " + ", ".join(AI_TELLS_TO_AVOID['empty_intensifiers'][:6]) + "\n"
    guide += "- Openers: " + ", ".join([x.split("...")[0] for x in AI_TELLS_TO_AVOID['hollow_openers'][:4]]) + "\n\n"

    # Natural writing patterns
    guide += "### DO USE THESE (Human Patterns):\n"
    for pattern in HUMAN_WRITING_PATTERNS['sentence_variety'][:4]:
        guide += f"- {pattern}\n"
    guide += "\n"

    # Specificity
    guide += "### BE SPECIFIC:\n"
    for rule in HUMAN_WRITING_PATTERNS['specificity_rules'][:3]:
        guide += f"- {rule}\n"
    guide += "\n"

    # Section-specific tone
    if section_type and section_type in SECTION_TONE_CALIBRATION:
        section = SECTION_TONE_CALIBRATION[section_type]
        guide += f"### TONE FOR THIS SECTION: {section['tone'].upper()}\n"
        for rule in section['rules']:
            guide += f"- {rule}\n"
        guide += "\n"

        # Add before/after example if available
        if section_type in HUMANIZATION_EXAMPLES:
            ex = HUMANIZATION_EXAMPLES[section_type]
            guide += "### EXAMPLE - DON'T vs DO:\n"
            guide += f"DON'T: \"{ex['ai_style'][:100]}...\"\n"
            guide += f"DO: \"{ex['human_style'][:100]}...\"\n"

    return guide


def get_full_style_guide_for_section(section_type):
    """
    Get the complete style guide for a section, combining structure + humanization.

    Args:
        section_type: Section name

    Returns:
        Complete formatted style guide for AI prompts
    """
    # Get the existing style guide
    guide = get_style_guide_for_prompt(section_type)

    # Add humanization guidelines
    guide += get_humanization_guidelines(section_type)

    return guide
