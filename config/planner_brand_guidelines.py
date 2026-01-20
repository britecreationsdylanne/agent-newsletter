"""
BriteCo Planner Pulse - Editorial Style Guide
Adapted for wedding planners and event professionals
"""

BRAND_GUIDELINES = {
    "numbers": {
        "rules": [
            "Use the percent symbol (%) rather than typing out 'percent'",
            "For ages, use numbers rather than spelling out",
            "For zero, spell out rather than using a number",
            "For phone number, only provide BriteCo's main number: (312) 809-9100"
        ],
        "correct_examples": [
            "71% of jewelers",
            "She is 58-years-old",
            "We offer zero deductibles"
        ],
        "incorrect_patterns": [
            r"seventy[- ]one percent",
            r"fifty[- ]eight[- ]years[- ]old",
            r"\$0 deductibles"
        ]
    },

    "abbreviations": {
        "rules": [
            "For country abbreviations, do not use periods (US, UK not U.S., U.K.)",
            "For Washington, DC, do not use periods"
        ],
        "corrections": {
            r"U\.S\.": "US",
            r"U\.K\.": "UK",
            r"D\.C\.": "DC"
        }
    },

    "punctuation": {
        "rules": [
            "Use a serial comma when writing out a list",
            "Use an em dash (—) with spaces around it, not hyphen",
            "Put names of movies, books, and periodicals in italics, not quotes",
            "Put punctuation inside quotation marks",
            "Use a hyphen between two words modifying the noun",
            "Always hyphenate lab-grown"
        ],
        "correct_examples": [
            "theft, loss, and damages",
            "Engagement rings — while pricey — are a worthwhile investment",
            "Our CEO recently published on Forbes",
            'Our tagline is, "Modern protection for modern milestones."',
            "5-star ratings",
            "budget-friendly policies",
            "lab-grown diamonds"
        ],
        "incorrect_patterns": [
            r"theft, loss and damages",  # Missing serial comma
            r"—(?! )|\S—\S",  # Em dash without spaces
            r'"Forbes\."',  # Quoted periodical
            r'lab grown',  # Not hyphenated
        ]
    },

    "title_case": {
        "rules": [
            "Headlines (H1s, H2s, H3s) use Title Case",
            "All other copy uses sentence case"
        ],
        "tool": "https://titlecaseconverter.com/"
    },

    "brand_names": {
        "corrections": {
            "OMEGA Watches": "Omega Watches"
        }
    },

    "briteco_brand": {
        "do": [
            "Call BriteCo an 'insurtech company' or 'insurance provider'",
            "Refer to BriteCo as a 'specialty jewelry insurance provider' when comparing to general insurers",
            "Say 'backed by an AM Best A+ rated Insurance Carrier'",
            "Refer to website as brite.co or https://brite.co",
            "Spell it stand-alone (not standalone)"
        ],
        "dont": [
            "Call BriteCo an 'insurance company'",
            "Refer to BriteCo as 'specialized jewelry insurance'",
            "Slander competitors or link to them (e.g. Jewelers Mutual)",
            "Say 'we have AM Best policies' or 'we are AM Best'",
            "Refer to website as www.brite.co",
            "Use standalone or stand-alone"
        ],
        "forbidden_terms": [
            "insurance company",
            "specialized jewelry insurance",
            "AM Best policies",
            "we are AM Best",
            "www.brite.co"
        ],
        "required_terms": {
            "insurtech company": ["insurance company"],
            "insurance provider": ["insurance company"],
            "specialty jewelry insurance provider": ["specialized jewelry insurance"],
            "backed by an AM Best A+ rated Insurance Carrier": ["AM Best policies", "we are AM Best"],
            "brite.co": ["www.brite.co"],
            "https://brite.co": ["www.brite.co"]
        }
    },

    "tone": {
        "wedding_insurance": {
            "rules": [
                "Be inclusive and use gender-less verbiage (they, them, theirs)",
                "Use 'wedding party' rather than 'bridal party'",
                "Say 'groom crew' over 'groomsmen'",
                "Rather than bride and groom, say partner, soon-to-be spouse"
            ],
            "corrections": {
                "bridal party": "wedding party",
                "groomsmen": "groom crew",
                "bride and groom": "partner",
                "bride": "partner",
                "groom": "partner"
            }
        },
        "jewelry": {
            "rules": [
                "When mentioning health claims, never promise results",
                "Use softer language: 'is known for', 'may be helpful with', 'has been seen to'"
            ],
            "avoid_patterns": [
                r"will increase",
                r"will boost",
                r"guarantees",
                r"proven to"
            ]
        }
    },

    "glossary": {
        "correct_terms": {
            "Homeowners policy": ["Homeowner's", "Homeowners'"],
            "Renters insurance": ["Renter's", "Renters'"],
            "stand-alone": ["standalone", "stand alone"]  # Note: PDF shows inconsistency
        }
    }
}

# Brand voice characteristics for AI content generation
BRAND_VOICE = {
    "tone": "Professional but warm, informative, approachable",
    "style": "Clear, concise, helpful",
    "perspective": "We help wedding planners and event professionals succeed",
    "avoid": [
        "Overly salesy language",
        "Jargon without explanation",
        "Promises we can't keep",
        "Gendered language",
        "Competitor comparisons"
    ]
}

# Newsletter-specific guidelines
NEWSLETTER_GUIDELINES = {
    "sections": {
        "news": {
            "structure": [
                "The Short Version: [one sentence summary]",
                "What's Happening: [2-3 paragraphs]",
                "Why It Matters for Planners: [practical takeaway for event planning professionals]"
            ],
            "tone": "Informative, newsworthy, relevant to wedding planners and event professionals"
        },
        "tip": {
            "structure": [
                "Title",
                "Subtitle: [actionable summary]",
                "Content: [2-3 paragraphs]",
                "CTA: Read More →"
            ],
            "tone": "Helpful, actionable, expert advice for planners"
        },
        "trend": {
            "structure": [
                "Title",
                "Subtitle: [trend description]",
                "Content: [2-3 paragraphs]",
                "CTA: Read More →"
            ],
            "tone": "Trend-forward, seasonal, inspiring for planners"
        }
    },
    "formatting": {
        "headlines": "Title Case",
        "body": "Sentence case",
        "sections": "Use italics for section labels"
    }
}
