# BriteCo Brief Fixes Plan

## Issue 1: Content Generation - Wrong Length/Style

### Current State
Based on your examples:

**Curious Claims** (Example: "A Shot for the Ages")
- Current prompt: Targets ~150-200 words, structured as briefing
- Example shows: 5-6 paragraphs, storytelling style, ~350-400 words
- Has engaging intro, plot twist, resolution, moral/takeaway

**News Roundup**
- Current prompt: ~25 words per bullet, plain summary
- Example shows: Catchy titles with hyperlinks, treat as headline-style
- Format: "Title phrase, and [Hyperlink Text](URL) describes what..."

**Agent Advantage**
- Current prompt: ~30 words per tip, simple format
- Example shows: Structured with mini-title (bold), 1-3 supporting sentences
- Has intro paragraph, 5 numbered points with sub-bullets, optional closing

### Plan
1. Update **Curious Claims prompt** in `/api/research-articles`:
   - Change from briefing format to storytelling narrative
   - Target 350-400 words
   - Structure: Hook intro → Story development → Plot twist → Resolution → Agent takeaway

2. Update **News Roundup prompt** in `/api/research-articles`:
   - Change from plain summary to headline-style with hyperlinks
   - Format each as: "[Catchy sentence], and [Source Name](URL) [continuation]"
   - Keep 5 bullet points

3. Update **Agent Advantage prompt** in `/api/research-articles`:
   - Add intro paragraph generation
   - Each tip: Bold mini-title (up to 10 words) + 1-3 supporting sentences
   - Optional closing sentence

---

## Issue 2: Spotlight Story - Verify Structure

### Current State
Spotlight from `/api/generate-spotlight`:
- Sub-header (15 words)
- 2-4 H3 sections with 1-2 paragraphs each
- Agent takeaway
- Target: 250-300 words

### Your Example Shows
- Title + sub-header
- 4-5 H3 sections with multiple paragraphs
- Multiple hyperlinks throughout
- "Implications for Agents" section
- Much longer (~500-600 words)

### Plan
- Update spotlight prompt to match longer format (~500-600 words)
- Ensure H3 sections have more substantial content
- Add more hyperlink placeholders throughout

---

## Issue 3: Brand Guidelines Checker

### Current State (briteco-brief)
- Returns simple pass/fail with plain text details
- No structured suggestions array

### Venue-Voice Implementation
- Returns JSON with `suggestions` array
- Each suggestion has: section, issue, original, suggested, reason
- Frontend highlights and allows accept/ignore

### Plan
1. Update `/api/brand-check` backend to match venue-voice:
   - Return structured JSON with `suggestions` array
   - Include P&C insurance-specific guidelines (not wedding)
   - Check for: tone, P&C focus, avoid health/life insurance mentions

2. Update frontend `displayBrandCheckResults()`:
   - Restore structured suggestions display
   - Add highlighting of issues
   - Add accept/ignore functionality

---

## Issue 4: Image Generation Failing

### Root Cause
Frontend uses wrong variable names:
- Uses: `selectedNews`, `selectedTip`, `selectedTrend`
- Should use: `selectedClaims`, `selectedRoundup`/`selectedSpotlight`, `selectedTips`

These variables are undefined, causing the API call to fail.

### Plan
1. Fix variable mappings in image prompt generation:
   - Map `claims` → Curious Claims section
   - Map `spotlight` → InsurNews Spotlight section
   - Map `tips` → Agent Advantage section
   - Map `roundup` → News Roundup (if images needed)

2. Update section names passed to API to match briteco-brief sections

---

## Summary of Files to Modify

1. **app.py** (backend):
   - `/api/research-articles`: Update prompts for claims, roundup, tips
   - `/api/generate-spotlight`: Increase word count, add more structure
   - `/api/brand-check`: Rewrite to return structured suggestions JSON

2. **index.html** (frontend):
   - Fix variable names in image generation section
   - Update `displayBrandCheckResults()` to handle structured suggestions
   - Potentially restore highlight functionality

---

## Questions Before Proceeding

1. For **News Roundup**, should each bullet have its own image, or is it just a text section?

2. For **Image Generation**, which sections should have images?
   - Curious Claims?
   - InsurNews Spotlight?
   - Agent Advantage?
   - All of the above?

3. The brand guidelines for P&C insurance - do you have specific rules like venue-voice has for weddings? (e.g., specific terminology, tone requirements, things to avoid)
