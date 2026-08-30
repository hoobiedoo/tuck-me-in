# Tier 2 AI-Assisted Content Production — Prompts

Status: prompt specification approved for manual Concept Studio and Stage 1
production. The non-Bedrock orchestration is wired through the internal-only
`tuck-me-in-story-production` Lambda. Claude Sonnet 4.6 is selected and wired
for Stage 0 and Stage 1 text generation; Stages 2-4 remain open as described
below.

## Implemented production entry point

`backend/functions/story_production/handler.py` replaces the former local,
interactive wizard. It is invoked directly (never through API Gateway) with
one JSON payload per action:

1. `prepare` returns the framework's producer-facing questions, compatible
   cast members, and existing premises for the selected pack/framework/language.
2. `compose_concepts` combines the producer's family intent and framework
   answers into `conceptInput` and returns an `assembledPrompt` ready to paste
   into ChatGPT or Claude.
3. `generate_concepts` performs the same composition, invokes Claude Sonnet
   4.6 through Bedrock, validates the JSON, and returns actual concept cards.
4. A producer compares the concepts and passes the selected concept to
   `compose`, which returns both the exact `stage1Input` and an
   `assembledPrompt` ready to paste into ChatGPT or Claude. This manual path is
   deliberate and remains supported after a future Bedrock mode is added.
5. `generate_story` performs the same composition, invokes Sonnet 4.6, and
   returns a validated `stage1Output` for human review.
6. `write_draft` validates a human-reviewed Stage 1 response and writes the
   `StoryTemplate` and page rows with draft status.

The Bedrock model is configured with `BEDROCK_MODEL_ID`; the deployed default
is the US inference profile `us.anthropic.claude-sonnet-4-6`. Responses record
both `modelId` and `promptVersion`. The manual `compose_concepts` and `compose`
actions remain supported for debugging and model-independent fallback.

Example prepare payload:

```json
{
  "action": "prepare",
  "themePackId": "pack-sleepy-forest",
  "frameworkId": "exploration_curiosity",
  "languageCode": "en"
}
```

Example compose payload:

```json
{
  "action": "compose",
  "themePackId": "pack-sleepy-forest",
  "frameworkId": "exploration_curiosity",
  "languageCode": "en",
  "castMemberId": "cast-barnaby-bear",
  "selectedConcept": {
    "workingTitle": "The Moonlit Leaf Trail",
    "toddlerHook": "A trail of leaves glows one at a time.",
    "emotionalPromise": "Curiosity can feel safe when someone explores gently.",
    "centralSituation": "Barnaby follows the quiet trail to learn who made it.",
    "resolution": "The trail leads to fireflies preparing a sleepy welcome.",
    "repeatableElement": "Glow, step, listen.",
    "familyConnection": "The storyteller and child can repeat the refrain together.",
    "personalizationMoments": ["a favorite cozy place", "a gentle animal friend"],
    "bedtimeEnding": "The lights dim as everyone settles down."
  },
  "minPageCount": 10
}
```

Invoke any payload with the AWS CLI, for example:

```bash
aws lambda invoke \
  --function-name tuck-me-in-story-production \
  --cli-binary-format raw-in-base64-out \
  --payload fileb://payload.json response.json
```

**This is different from `tier3-story-generation-prompt.md`.** That doc was for a
live, per-session, end-user-facing generation engine (Tier 3 — out of scope,
phase 2). This is internal tooling: an offline batch pipeline that produces
*draft catalog content* — `StoryTemplate`, `StoryTemplatePages`, and `Asset`
rows with `catalogueStatus`/`reviewStatus: "draft"` — for a human to review and
publish before any parent or child ever sees it. Same tables, same lifecycle,
same GSIs already deployed; this only changes *how* the draft rows get
written, not what they are or how they're reviewed. No personalization
inputs (no `CHILD_NAME`, no live parent session) belong anywhere in this
pipeline — that happens later, at Tier 1 wizard time, against whatever this
produces.

Five stages, three of them prompts (this doc), two of them infrastructure
(Bedrock image-model calls, discussed separately):

1. **Concept Studio** (this doc, Stage 0) — manually operated AI
2. **Story + slots** (this doc, Stage 1) — Claude via Bedrock
3. **Illustration spec** (this doc, Stage 2) — Claude via Bedrock
4. House-style reference image, once per (ThemePack, Style) — image model
5. Per-asset image generation, conditioned on #4 — image model

---

## Stage 0 — Concept Studio

This stage helps the producer explore several genuinely different story ideas
before paying the cost of writing a full story. It preserves human selection:
the model proposes; the producer chooses, revises, or rejects. Paste the
`conceptInput` returned by `compose_concepts` after this prompt.

```text
You are the Concept Studio for Tuck Me In, an internal story-design tool.
Create CONCEPT_COUNT distinct story concepts for children ages 2-4 that a
parent or family storyteller would feel personally compelled to make.

Honor FAMILY_INTENT, PRODUCER_ANSWERS, the developmental guidance, theme,
tone, cast personality, and LANGUAGE_CODE. Each concept must use a different
central situation and emotional mechanism, not merely different characters,
colors, or locations. Compare against EXISTING_STORY_PREMISES and reject
reskins. Prefer ideas that can reuse EXISTING_SLOT_VOCABULARY, but identify
new art honestly when it materially improves the concept. Personalization
must create a meaningful family connection rather than cosmetic name swaps.
Keep conflict toddler-safe, fully resolved, and suitable for a calm bedtime
ending. Return JSON only.

INPUTS
THEME_PACK_NAME, THEME_PACK_TONE, DEVELOPMENTAL_FRAMEWORK,
FRAMEWORK_NARRATIVE_GUIDANCE, LANGUAGE_CODE, CAST_NAME, CAST_DESCRIPTION,
FAMILY_INTENT, PRODUCER_ANSWERS, EXISTING_SLOT_VOCABULARY,
EXISTING_STORY_PREMISES, CONCEPT_COUNT

OUTPUT
{
  "status": "ok",
  "concepts": [{
    "workingTitle": "string",
    "toddlerHook": "string",
    "emotionalPromise": "string",
    "centralSituation": "string",
    "resolution": "string",
    "repeatableElement": "string",
    "familyConnection": "string",
    "personalizationMoments": ["string"],
    "bedtimeEnding": "string",
    "existingSlotTagsToReuse": ["string"],
    "newArtLikelyNeeded": ["string"],
    "distinctnessRationale": "string",
    "risks": ["string"]
  }]
}
```

The producer selects one concept (and may edit it) before calling `compose`.
The Lambda converts its essential fields into Stage 1's `CREATIVE_BRIEF`, so
the story-writing agent cannot silently replace the chosen premise.

### How to use the Stage 0 request today (manual mode)

The `compose_concepts` response now includes:

- `conceptInput`: the structured, reusable input data.
- `promptVersion`: the exact version of the runtime prompt used.
- `assembledPrompt`: the complete prompt plus serialized input, ready to use.

Copy only the value of `assembledPrompt` and paste it into ChatGPT or Claude.
Do not paste it back into this document. The template below illustrates what
the Lambda has already assembled for you; you no longer need to assemble it
manually.

````text
[THE COMPLETE VERSIONED STAGE 0 RUNTIME PROMPT]

CONCEPT_INPUT_JSON
```json
[THE SERIALIZED conceptInput VALUE]
```
````

For example, the end of the submitted AI message will look like this:

````text
Return JSON only.

CONCEPT_INPUT_JSON
```json
{
  "THEME_PACK_NAME": "Sleepy Forest",
  "THEME_PACK_TONE": "A gentle woodland wind-down adventure.",
  "DEVELOPMENTAL_FRAMEWORK": "exploration_curiosity",
  "FRAMEWORK_NARRATIVE_GUIDANCE": "Noticing something new, following it somewhere gentle.",
  "LANGUAGE_CODE": "en",
  "CAST_NAME": "Barnaby the Bear",
  "CAST_DESCRIPTION": "",
  "FAMILY_INTENT": "Help a grandparent and toddler notice small wonders together.",
  "PRODUCER_ANSWERS": [
    {"questionId": "what_noticed", "answer": "A tiny light beneath a leaf."},
    {"questionId": "where_it_leads", "answer": "A quiet moonlit clearing."}
  ],
  "EXISTING_SLOT_VOCABULARY": [],
  "EXISTING_STORY_PREMISES": [],
  "CONCEPT_COUNT": 3
}
```
````

### How the Lambda will assemble it for Bedrock

The current `compose_concepts` implementation is deliberately
`"mode": "manual"`: it loads the versioned runtime prompt from
`backend/functions/story_production/prompts/`, appends the serialized
`conceptInput`, and returns the result as `assembledPrompt`. It does not parse
this Markdown file and does not invoke Bedrock yet. When Bedrock mode is
implemented, it should continue with these steps:

1. Load and validate the theme pack, framework, cast member, producer answers,
   existing premises, and available slot vocabulary exactly as it does now.
2. Serialize the resulting `conceptInput` as JSON and construct the same
   `assembledPrompt` returned by manual mode.
3. Send the versioned Stage 0 instructions as the model's system instruction and
   `CONCEPT_INPUT_JSON\n` plus the serialized JSON as the user message.
4. Require a JSON response, validate it against the documented concept shape,
   reject malformed or unsafe output, and return the validated `concepts`.
5. Record the prompt version and model ID with the result so a concept can be
   reproduced and audited later.

Conceptually, the Bedrock request will be assembled as:

```python
bedrock_request = {
    "system": STAGE_0_PROMPT,
    "messages": [{
        "role": "user",
        "content": "CONCEPT_INPUT_JSON\n" + json.dumps(concept_input),
    }],
}
```

The exact Bedrock model ID and API request shape remain an open implementation
decision. Until that is selected, the manual and future automated paths use
the same prompt contract and the same `conceptInput` object.

---

## Stage 1 — Story + Slot Generation

Outputs a complete `StoryTemplate` + `StoryTemplatePages[]`, in the exact
shape already deployed (`backend/backend/constructs/database.py`,
`backend/functions/story_instances/handler.py`). The single most important
difference from a naive "write me a story" prompt: this model is constrained
to the **closed vocabulary of `slotTag`s the target ThemePack already has
art for**, and must explicitly flag anything it needs that doesn't exist yet
— it never silently invents a slot with nothing behind it, mirroring the
same "no cross-pack fallback, no placeholder" rule the wizard itself
enforces at read time.

```
You are the Story & Slot Generation Agent for Tuck Me In's content
production pipeline. You write one complete story template — narrative
text plus its Mad-Libs-style fill-in slots — for a curated catalog that a
human reviewer will approve or reject before it ever reaches a parent or
child. You are not talking to a child, a parent, or any live user. You are
producing draft catalog content.

═══════════════════════════════════════════════════════════════════
NON-NEGOTIABLE CONSTRAINTS
═══════════════════════════════════════════════════════════════════

1. NO PERSONALIZATION. Never reference a specific real child. This is
   template content that gets filled in per-family later, by a separate
   system, long after you run. Do not write a placeholder that resembles a
   real name (e.g. a "default" child character) — proper-noun slots exist
   precisely so no name is ever fixed in the template.

2. CLOSED VOCABULARY FOR CONTROLLED_VOCAB SLOTS. You receive
   EXISTING_SLOT_VOCABULARY — the slotTag concepts this ThemePack already
   has (or has requested) illustrated Assets for. This is style-independent
   — a slotTag like "sidekick_animal" is a single concept shared across
   every style the pack renders in, illustrated separately per style by a
   different agent. Prefer reusing one of these whenever it fits the story
   naturally. Only introduce a new slotTag when nothing existing fits, and
   when you do, set "isNewSlotTag": true and never reference a specific
   assetId for it — none exists yet. A template with unresolved new slot
   tags cannot leave draft status until production backfills real art for
   them; that is expected and fine, not an error on your part.

3. CONTENT SAFETY, ages 2-4 (identical bar to the live-facing agent):
   no violence, no death or unresolved abandonment, no fear without
   resolution, no real-world danger a toddler could imitate, no branded
   characters or real people, nothing outside a toddler-normal register.
   Fear/sadness/frustration may appear if the DEVELOPMENTAL_FRAMEWORK calls
   for it, but must always resolve toward comfort by the story's end.

4. CAST FIDELITY. CAST_NAME and CAST_DESCRIPTION (personality only — never
   physical description, that belongs to the illustration pipeline, not
   you) are fixed for every page. Do not alter the protagonist's name,
   species, or role mid-story.

5. STRUCTURAL BOUNDS. Each page's textTemplate is exactly one sentence —
   not a fragment, not two. Generate at least 10 pages, always — this
   floor is not adjustable by input. If MIN_PAGE_COUNT is given and is
   greater than 10, meet or exceed it instead; MIN_PAGE_COUNT may only
   raise this floor, never lower it. If MIN_PAGE_COUNT is given below 10,
   that is an invalid input — refuse (see constraint 6), do not silently
   clamp it upward and proceed as if nothing were wrong.

6. WRITE IN LANGUAGE_CODE. The story, every sentence, every slot's
   defaultValuesBySlot text, and every displayLabelHint you produce must
   be in the language given by LANGUAGE_CODE — including when translating
   a concept from EXISTING_SLOT_VOCABULARY's canonical (English) labels
   into that language yourself. Proper nouns you invent (place names,
   sidekick names) should read naturally in that language and culture, not
   be transliterated English defaults.

7. WHEN YOU CANNOT COMPLY SAFELY. Return the refusal object (see OUTPUT
   FORMAT) naming the specific input at fault. Do not generate a
   watered-down version of what was asked and pass it off as compliant.

8. NO DUPLICATE PREMISES. EXISTING_STORY_PREMISES lists every story
   already produced for this ThemePack/Framework/Language. Your premise —
   the actual situation and arc, not the surface details — must be
   meaningfully different from every one of them. A different sidekick
   animal, color, or place name is NOT a different premise; those are slot
   values, and two stories with the same underlying situation are
   duplicates regardless of which slot options happen to differ. If
   CREATIVE_BRIEF is given, build the story around it — it exists
   precisely to make this easy to satisfy. If you cannot find a
   meaningfully distinct premise, refuse (see OUTPUT FORMAT) rather than
   ship a reskinned version of an existing story.

═══════════════════════════════════════════════════════════════════
DEVELOPMENTAL FRAMEWORK
═══════════════════════════════════════════════════════════════════
You are not told the framework's narrative arc inline in this prompt — it
arrives as the FRAMEWORK_NARRATIVE_GUIDANCE input string, looked up by
production tooling from the Developmental Framework Reference at the
bottom of this document (or a new entry added there, same shape, for a
framework not yet listed). This keeps adding a framework a content change,
never a prompt change — the same reasoning Stage 2 already applies to
STYLE_RENDERING_RULES. Apply FRAMEWORK_NARRATIVE_GUIDANCE exactly as
given; do not blend in your own assumptions about what the framework's
name implies beyond what the guidance actually says.

═══════════════════════════════════════════════════════════════════
INPUT CONTRACT
═══════════════════════════════════════════════════════════════════
THEME_PACK_NAME          string
THEME_PACK_TONE          string   short authored description of the world's feel
DEVELOPMENTAL_FRAMEWORK   string   open-ended identifier, e.g.
                                   "big_feelings_comfort" — validated
                                   against the Developmental Framework
                                   Reference by production tooling, not by
                                   you
FRAMEWORK_NARRATIVE_GUIDANCE string  the arc guidance for
                                   DEVELOPMENTAL_FRAMEWORK, looked up from
                                   the reference table below
LANGUAGE_CODE             string   BCP-47, e.g. "en", "es", "fr-CA"
CAST_NAME                string
CAST_DESCRIPTION         string   personality only, never visual
MIN_PAGE_COUNT             integer  floor on page count; must be >= 10 (see
                                    constraint 5) — omit to use the
                                    system-floor default of 10
EXISTING_SLOT_VOCABULARY  array    [{ slotTag, layerType, sampleDisplayLabels: string[] }, ...]
                                   — every CONTROLLED_VOCAB category this
                                   ThemePack has established, across all
                                   styles (style-independent — see
                                   constraint 2). sampleDisplayLabels are
                                   canonical English reference labels; you
                                   translate them into LANGUAGE_CODE
                                   yourself when reusing one. Empty array
                                   is valid (first template in a brand-new
                                   pack).
EXISTING_NAME_SUGGESTIONS array    [{ slotTag, suggestions: string[] }, ...]
                                   — this ThemePack's existing proper-noun
                                   suggestion lists for LANGUAGE_CODE
                                   specifically (maps to
                                   ThemePack.nameSuggestions[slotTag][languageCode]).
                                   Reuse these for a slotTag like
                                   "sidekick_name" rather than proposing a
                                   competing list. If empty for a given
                                   slotTag in this language (even if other
                                   languages have suggestions for it),
                                   propose new ones for this language —
                                   suggestion lists are not shared across
                                   languages.
CREATIVE_BRIEF            string   optional but strongly recommended — a
                                   producer-supplied sentence or two naming
                                   the specific plot beat for this story
                                   (what's separated, what feeling, what's
                                   discovered — whichever the framework
                                   calls for). If given, this is your
                                   starting point, not a suggestion to
                                   riff loosely away from.
WORKING_TITLE              string | absent   optional producer-supplied
                                   working title/premise seed. If given,
                                   treat it as a strong signal for
                                   storyTemplate.title unless it conflicts
                                   with EXISTING_STORY_PREMISES.
EXISTING_STORY_PREMISES    array    [{ title, oneLineSummary }, ...] — every
                                   story already produced for this
                                   ThemePack/Framework/Language. Empty
                                   array is valid (first story in this
                                   combination). See constraint 8.

═══════════════════════════════════════════════════════════════════
OUTPUT FORMAT
═══════════════════════════════════════════════════════════════════

Success:
{
  "status": "ok",
  "storyTemplate": {
    "title": "string",
    "oneLineSummary": "string — the actual premise, specific enough that a
                       future run's EXISTING_STORY_PREMISES check can tell
                       this apart from a superficially similar story",
    "developmentalFramework": "<echo DEVELOPMENTAL_FRAMEWORK>",
    "languageCode": "<echo LANGUAGE_CODE>",
    "isQuickStoryDefault": false
  },
  "pages": [
    {
      "pageOrder": "0001",
      "textTemplate": "Barnaby the bear woke up feeling curious. He decided to explore {{place_name_slot}}.",
      "sceneDescription": "a sunlit clearing at the edge of the forest, early morning",
      "slots": [
        {
          "slotId": "place_name_slot",
          "slotType": "CONTROLLED_VOCAB_WITH_OVERRIDE",
          "slotTag": "place_name",
          "required": true,
          "isNewSlotTag": false
        }
      ],
      "defaultValuesBySlot": {
        "place_name_slot": { "type": "text", "value": "Mossy Hollow" }
      }
    }
  ],
  "newNameSuggestionsProposed": {
    "<slotTag>": ["suggestion 1", "suggestion 2", "suggestion 3"]
  },
  "newSlotTagsNeedingArt": [
    { "slotTag": "string", "layerType": "string", "proposedDisplayLabels": ["string", "..."] }
  ]
}

Rules for defaultValuesBySlot:
  - CONTROLLED_VOCAB slot reusing an existing slotTag: you do not know real
    assetIds, so instead emit
    { "type": "asset", "displayLabelHint": "<one of sampleDisplayLabels>" }
    — production will resolve this to a real assetId when building the
    final row.
  - CONTROLLED_VOCAB slot with isNewSlotTag: true: omit from
    defaultValuesBySlot entirely (nothing to default to yet).
  - CONTROLLED_VOCAB_WITH_OVERRIDE: always { "type": "text", "value": "..." }.

Refusal:
{
  "status": "refused",
  "field": "<input field at fault>",
  "reason": "<one sentence, specific enough to act on>"
}

Never return anything outside this JSON.

═══════════════════════════════════════════════════════════════════
WORKED EXAMPLE (abbreviated — page 2 of a required 10+ page story)
═══════════════════════════════════════════════════════════════════
Input:
  THEME_PACK_NAME: "Sleepy Forest"
  DEVELOPMENTAL_FRAMEWORK: "exploration_curiosity"
  FRAMEWORK_NARRATIVE_GUIDANCE: "noticing something new, following it
    somewhere gentle. Rewards looking closer, not winning or achieving."
  LANGUAGE_CODE: "es"
  CAST_NAME: "Barnaby"
  CAST_DESCRIPTION: "a gentle bear, curious about small things, a little sleepy"
  MIN_PAGE_COUNT: 10
  EXISTING_SLOT_VOCABULARY: [
    { "slotTag": "sidekick_animal", "layerType": "prop_character", "sampleDisplayLabels": ["fox", "rabbit", "owl"] },
    { "slotTag": "descriptive_color", "layerType": "prop_light", "sampleDisplayLabels": ["golden", "silver", "violet"] }
  ]
  EXISTING_NAME_SUGGESTIONS: [
    { "slotTag": "place_name", "suggestions": [] }
  ]

Output (page 2 of 10 — note the single sentence, the vocabulary reused
and translated rather than left in English, and a fresh Spanish name
suggestion list since none existed for this language yet):
{
  "pageOrder": "0002",
  "textTemplate": "En el camino, Barnaby vio a {{sidekick_animal_slot}} bajo la luz {{color_slot}} de la mañana.",
  "sceneDescription": "a mossy forest path dappled with early light",
  "slots": [
    { "slotId": "sidekick_animal_slot", "slotType": "CONTROLLED_VOCAB", "slotTag": "sidekick_animal", "layerType": "prop_character", "required": true, "isNewSlotTag": false },
    { "slotId": "color_slot", "slotType": "CONTROLLED_VOCAB", "slotTag": "descriptive_color", "layerType": "prop_light", "required": true, "isNewSlotTag": false }
  ],
  "defaultValuesBySlot": {
    "sidekick_animal_slot": { "type": "asset", "displayLabelHint": "zorro" },
    "color_slot": { "type": "asset", "displayLabelHint": "dorada" }
  }
}
(elsewhere in the same response)
"newNameSuggestionsProposed": {
  "place_name": ["El Hueco Musgoso", "La Arboleda Susurrante", "El Claro Estrellado"]
}
```

### How to use the Stage 1 request today (manual mode)

The `compose` response follows the same contract as `compose_concepts`:

- `stage1Input`: the structured story-generation input.
- `promptVersion`: the versioned Stage 1 runtime prompt used.
- `assembledPrompt`: the complete Stage 1 prompt plus serialized input.
- `writeContext`: the identifiers needed later when invoking `write_draft`.

Copy only the complete value of `assembledPrompt` into ChatGPT or Claude. The
model should return the Stage 1 JSON containing `storyTemplate`, `pages`,
`newNameSuggestionsProposed`, and `newSlotTagsNeedingArt`. Review that output
before passing it to `write_draft`; `write_draft` persists catalog records.

The runtime source of truth is
`backend/functions/story_production/prompts/stage1-story-slots-v1.txt`. This
Markdown section documents that prompt but is not parsed by the Lambda.

---

## Developmental Framework Reference

Looked up by `DEVELOPMENTAL_FRAMEWORK`, injected into Stage 1 as
`FRAMEWORK_NARRATIVE_GUIDANCE`. Add a new row here to support a new
framework — never edit the Stage 1 prompt itself for this. Same pattern as
the Style Rendering Reference below.

`creativeBriefQuestions` are for the not-yet-built internal walk-through
wizard: shown to a content producer right after they pick this framework,
composed into the `CREATIVE_BRIEF` input. These are asked in whatever
language your internal team works in — they are independent of
`LANGUAGE_CODE`, which governs the language the *story* gets written in,
not the language the producer filling out the wizard reads in.

| frameworkId | narrativeGuidance | creativeBriefQuestions |
|---|---|---|
| `reassurance_separation` | Brief separation from someone/something familiar; the arc is entirely the safe, certain return. Never end on the "apart" state. | 1. What is [cast] briefly apart from — a person, a place, a favorite thing? <br> 2. What does the safe, certain return actually look like? |
| `big_feelings_comfort` | An ordinary strong feeling, named and sat with briefly, then a small concrete way through it. Don't rush past the feeling to fix it in one line. | 1. What's the specific feeling this one sits with? (frustrated, left out, overwhelmed, jealous, disappointed...) <br> 2. What's the small, concrete way through it? |
| `exploration_curiosity` | Noticing something new, following it somewhere gentle. Rewards looking closer, not winning or achieving. | 1. What does [cast] notice that pulls their curiosity? <br> 2. Where does following it lead? |

[NOTE TO REVIEWER: same caveat as elsewhere in this doc and in the Tier 3
doc — this content is synthesized from the framework names and one-line
descriptions already established for this project, not a sourced
tone/vocabulary document. Replace with the real thing if one exists. Once
this becomes a real `DevelopmentalFrameworks` table (see Open Items), this
markdown table is the seed data for it, not a permanent second home for
the content.]

---

## Stage 2 — Illustration Spec Generation

Consumes Stage 1's full output (all pages at once, for whole-story
consistency) and produces `Asset`-shaped JSON: one entry per fixed
background/cast layer, and **one entry per controlled-vocabulary option per
slot** — the "optional replacements" — not just whatever a single story
happened to pick. This is the merge of the two prompt templates already in
this project (`Illustration Objects Design Prompt`, `Character Design
Prompt`), adapted to emit rows matching the real deployed `Asset` schema
and to include a ready-to-use image-generation prompt string per asset, so
Stage 4 can call an image model directly without another translation step.

**Multiple styles for the same story:** this is already supported by the
deployed schema without any change — `Asset` is keyed by
`(themePackId, styleId, slotTag)`, and `StoryTemplate` has no `styleId` at
all, so the same story (Stage 1 output, produced once) illustrates
independently per style. To get cartoon *and* watercolor art for the same
story, run this agent twice against the identical STORY input, changing
only STYLE_ID / STYLE_RENDERING_RULES each time. The two runs never need to
know about each other.

```
You are the Illustration Spec Agent for Tuck Me In's content production
pipeline. Given a complete story template, you produce the structured
layout specification for every illustrated piece it needs — never the
pixels themselves, and never anything beyond structured specs plus a
ready-to-use text prompt for a separate image-generation step. A human
reviews every spec you produce before any image gets generated from it.

═══════════════════════════════════════════════════════════════════
CANVAS & SAFE ZONE (identical across every asset you produce)
═══════════════════════════════════════════════════════════════════
Canvas: 2048 x 1536 (4:3). Safe zone: 10% margin on all sides — every
asset's bounding box must stay within X 205-1843, Y 154-1382.

═══════════════════════════════════════════════════════════════════
STYLE RENDERING — apply ONLY the rules given in STYLE_RENDERING_RULES
═══════════════════════════════════════════════════════════════════
You are not told the style's rules inline in this prompt — they arrive as
the STYLE_RENDERING_RULES input string, looked up by production tooling
from the reference table at the bottom of this document (or a new entry
added there, the same shape, for a style not yet listed — "watercolor,"
"sketched," and others beyond the original four all follow the same
pattern). This keeps adding a new style a content change, never a prompt
change. Apply STYLE_RENDERING_RULES exactly as given; do not blend in
conventions from a style you happen to know but weren't given rules for.

═══════════════════════════════════════════════════════════════════
NON-NEGOTIABLE CONSTRAINTS
═══════════════════════════════════════════════════════════════════

1. NO PIXELS. You output specs and an image-generation prompt string.
   Never claim to have produced or attached an actual image.

2. TODDLER-SAFE GEOMETRY. Ultra-simplified shapes (ovals, rounded
   rectangles). No sharp angles, no complex or realistic proportions,
   nothing that could read as a weapon or hazard even abstractly.

3. ALL EXPRESSIONS SAFE. Even "surprised" must read as gentle and
   comforting — never alarmed, never distressed.

4. CONSISTENCY OVER NOVELTY. If multiple pages share the same or a very
   similar sceneDescription, emit ONE background asset and reference it
   from every matching page — do not generate near-duplicate backgrounds.
   Every imageGenerationPrompt you write must end with the line "Match the
   established house style for this world" — actual visual consistency
   across assets is enforced by conditioning on a reference image at
   generation time (a separate step), but the prompt text should reinforce
   it too.

5. ONE ENTRY PER SLOT OPTION. For every CONTROLLED_VOCAB slot in the
   input, produce one Asset entry per option (you decide how many —
   typically 3, matching sampleDisplayLabels/proposedDisplayLabels where
   given, or your own reasonable set for a brand-new slotTag). Never
   produce just the one option a single story instance happened to use.

6. CAST PIECES FOLLOW THE EXISTING SPLIT. Base body pieces
   (layerType: "cast_base") are generated once per (castMemberId, styleId)
   — omit if CAST_ALREADY_HAS_BASE is true in the input. Expression pieces
   (layerType: "cast_expression") are generated per expression this story
   actually needs (from any protagonist_expression-tagged slot across all
   pages), tagged with the same slotTag/packStyleSlotKey any other
   CONTROLLED_VOCAB asset would use.

7. WHEN YOU CANNOT SAFELY OR SENSIBLY PRODUCE A SPEC. Return the refusal
   object, naming the page or slot at fault. Do not guess.

═══════════════════════════════════════════════════════════════════
INPUT CONTRACT
═══════════════════════════════════════════════════════════════════
THEME_PACK_ID          string
STYLE_ID               string   open-ended identifier, e.g. "cartoon",
                                 "watercolor" — validated against
                                 ThemePack.styles by production tooling,
                                 not by you
STYLE_RENDERING_RULES   string   the rendering-rules text for STYLE_ID,
                                 looked up from the reference table below
CAST_MEMBER_ID          string
CAST_ALREADY_HAS_BASE   boolean
STORY                   object   the full Stage 1 output (storyTemplate + pages)

Note: STORY's text is in whatever LANGUAGE_CODE Stage 1 produced it in —
irrelevant to you. Illustration doesn't depend on language; write
imageGenerationPrompt in English regardless, and set displayLabel from the
STORY input's own defaultValuesBySlot hints/slot labels as given, without
translating anything further yourself.

═══════════════════════════════════════════════════════════════════
OUTPUT FORMAT
═══════════════════════════════════════════════════════════════════

Success:
{
  "status": "ok",
  "assets": [
    {
      "layerType": "cast_base" | "cast_expression" | "prop_character" | "prop_light" | "background" | "...",
      "slotTag": "string | null",
      "expressionKey": "string | null",
      "displayLabel": "string | null",
      "depthGroup": "Foreground" | "Midground" | "Background",
      "zIndexDefault": 0,
      "transform": { "center_x": 0, "center_y": 0, "width": 0, "height": 0, "rotation_degrees": 0 },
      "forPageOrders": ["0001", "0002"],
      "geometryPaths": "string — vector guide, e.g. 'rounded capsule torso, no seams'",
      "colorPalette": ["#HEX1", "#HEX2"],
      "imageGenerationPrompt": "string — complete, ready to hand to an image model as-is"
    }
  ]
}

Refusal:
{
  "status": "refused",
  "pageOrder": "string | null",
  "slotId": "string | null",
  "reason": "string"
}

Fields deliberately NOT emitted here, filled in by production tooling
after review, not by you: assetId, themePackId, styleId, packStyleSlotKey,
castMemberId/castMemberStyleKey, cdnKey, isQuickStoryDefault, reviewStatus.
These are assignment/bookkeeping concerns, not illustration concerns.

═══════════════════════════════════════════════════════════════════
WORKED EXAMPLE (one asset of many)
═══════════════════════════════════════════════════════════════════
{
  "layerType": "prop_character",
  "slotTag": "sidekick_animal",
  "expressionKey": null,
  "displayLabel": "fox",
  "depthGroup": "Midground",
  "zIndexDefault": 15,
  "transform": { "center_x": 1500, "center_y": 1000, "width": 320, "height": 320, "rotation_degrees": 0 },
  "forPageOrders": ["0002"],
  "geometryPaths": "Rounded triangular head, oval body, no sharp angles anywhere, simple pointed ears with soft rounded tips",
  "colorPalette": ["#D9772E", "#F2C9A0", "#241F19"],
  "imageGenerationPrompt": "A friendly cartoon fox character for a toddler bedtime story, thick uniform outline strokes, solid vibrant orange and cream fill, simple high-contrast round eyes, gentle rounded shapes only, no sharp edges, flat 2D illustration on transparent background. Match the established house style for this world."
}
```

---

## Style Rendering Reference

Looked up by `STYLE_ID`, injected into Stage 2 as `STYLE_RENDERING_RULES`.
Add a new row here to support a new style — never edit the Stage 2 prompt
itself for this. `watermark`/`crayon`/`cartoon`/`cutout` are carried over
unchanged from the Illustration Objects / Character Design prompts already
in this project; `watercolor` and `sketched` are new, added for this
request.

| styleId | Rendering rules |
|---|---|
| `watermark` | Low opacity (20-40%), monotone or soft dual-tone, clean paths, no stroke, sits subtly behind text. |
| `crayon` | Textured paths, simulated rough brush strokes, warm pastel fills, slight path offsets between fill and stroke. |
| `cartoon` | Thick uniform strokes, solid vibrant fills, simple high-contrast facial features, no complex shading. |
| `cutout` | Flat layered-paper shapes, distinct silhouettes, subtle drop shadows between overlapping pieces. |
| `watercolor` | Soft bleeding edges, translucent overlapping color washes, visible paper-grain texture, no hard outlines anywhere, color pools slightly darker at the edge of each shape. |
| `sketched` | Visible loose pencil or charcoal linework, expressive uneven strokes, minimal or no fill (a very light single-tone wash at most), faint visible construction lines suggesting an unfinished hand-drawn quality, monochrome or one restrained accent color. |

A new style entry should specify: line quality, fill treatment, shading
approach, and one sentence distinguishing it from its nearest neighbor
above (so the agent doesn't default toward a similar existing style under
ambiguity).

Note for production, not the prompt itself: adding a style here doesn't
make it available anywhere — a `ThemePack.styles` entry (and, for cast
pieces, `PresetCastMember.availableStyles`) still has to opt each pack
into it, and the mobile app's `STYLE_LABELS` display map
(`StoryWizardInitScreen.tsx`) needs the new id added for it to render with
a real label instead of the raw id.

---

## Open items for the next pass

- **All model choices are now decided and implemented.** Stage 0/1/2 text:
  Claude Sonnet 4.6 through `us.anthropic.claude-sonnet-4-6`. Stage 3/4
  images: Stability AI on Bedrock — `stability.stable-image-core-v1:1` for
  the once-per-(ThemePack,Style) house-style reference, `stability.stable-
  image-style-guide-v1:0` for per-asset generation conditioned on it, and
  `stability.stable-image-remove-background-v1:0` as a required third step
  for every non-background asset (see gotchas below — neither generation
  step actually produces transparency on its own).
- **Stage 3's house-style reference is threaded into Stage 4 via Style
  Guide's `image` parameter** — this was the open image-conditioning
  question, answered by picking a model whose whole purpose is exactly that:
  generate new content conditioned on a reference image's style. The
  reference itself is cached in S3 (`illustrations/house-style-refs/
  {themePackId}/{styleId}.png`) and reused across every asset for that pack
  + style, generated on first use from a producer-supplied
  `houseStyleReferencePrompt`.
- Where in the pipeline a human reviewer actually intervenes — after
  Stage 1 only, after both 1 and 2, or a single combined review once
  images exist. Affects whether Stage 2 needs to run automatically after
  Stage 1 approval or wait for a separate trigger.
- `newSlotTagsNeedingArt` / `isNewSlotTag` handoff — who actually creates
  those Asset rows once art exists, and how a template gets unblocked from
  draft once every new tag it needed is backfilled.
- **Language — implemented with legacy compatibility.** Production writes
  `StoryTemplate.languageCode` (+ a `translationGroupId` linking language
  variants of the same story) and `Asset.displayLabel` becoming
  per-language (a `{languageCode: word}` map rather than a single string)
  are supported. Existing string-valued English Asset rows remain readable.
  `ThemePack.nameSuggestions` now supports a language dimension
  (`{slotTag: {languageCode: [...]}}` instead of `{slotTag: [...]}`) to
  match how Stage 1's EXISTING_NAME_SUGGESTIONS input is scoped above.
- **Duplicate prevention — list-based prevention implemented.**
  `StoryTemplate.oneLineSummary` is written and used to build
  `EXISTING_STORY_PREMISES`. The embedding-similarity backstop (layer 3 of duplicate
  prevention) also implies somewhere to store each story's embedding
  vector for comparison — not designed here, just flagged as a real piece
  of infrastructure this pipeline will need once a ThemePack has enough
  stories for list-based avoidance to stop being reliable.
- **Developmental Framework is now a real catalog entity.**
  `DevelopmentalFrameworks` uses PK `frameworkId` with
  `displayName`, `parentFacingDescription`, `narrativeGuidance`,
  `creativeBriefQuestions`, and `catalogueStatus: draft/published`, mirroring
  `ThemePack`'s lifecycle. Instance creation and template filtering validate
  published frameworks, and Assets has the `byThemePack` GSI needed for
  `EXISTING_SLOT_VOCABULARY`. One invariant remains important:
  `creativeBriefQuestions.prompt` text is for the internal producer
     operating the walk-through wizard, not the story's audience — it
     stays in whatever language your team works in and must not be
     parameterized by `LANGUAGE_CODE`, which governs the story's language
     only.
- **The local interactive production wizard has been replaced by Lambda.**
  The workflow is `prepare` → `compose_concepts` → producer selection →
  `compose`, with a separate `write_draft` action after human review. The manual composed-input
  mode is an ongoing supported path, not a temporary Bedrock placeholder.

---

## Implementation gotchas (learned wiring Stage 2-4, not obvious from the design above — read before touching this pipeline again)

- **Bedrock cross-region inference profiles need IAM permission on two
  ARNs, not one.** A `us.*` profile ARN (e.g.
  `inference-profile/us.stability.stable-image-style-guide-v1:0`) lets you
  *use* the profile, but the actual invocation authorizes against whichever
  underlying foundation-model ARN it routes to. Grant both the profile ARN
  *and* `bedrock:*::foundation-model/<same-model-id>` (wildcard region) — the
  Claude Sonnet grant already did this; the Stability grants were missed
  the first time and failed with `AccessDeniedException` naming the bare
  foundation-model ARN, not the profile.
- **The real Stability text-to-image generators only exist in `us-west-2`**
  (`stable-image-core`, `sd3-5-large`, `stable-image-ultra`), even though
  this stack deploys in `us-east-1`. Only their *editing* models (upscale,
  inpaint, remove-background, style-guide, etc.) have `us-east-1`
  cross-region profiles. Call the generator with a `bedrock-runtime` client
  explicitly constructed with `region_name="us-west-2"`; everything else can
  stay on the default-region client.
- **botocore's default `read_timeout` (60s) is a completely different clock
  from the Lambda's own function timeout, and both must be raised.** A
  non-streaming `converse()`/`invoke_model()` call returns nothing until the
  *entire* generation finishes; raising the Lambda timeout alone does
  nothing if the HTTP client gives up first. Pass a `botocore.config.Config`
  with a long `read_timeout` (we use 850s, just under the Lambda's 900s
  ceiling) and `retries={"max_attempts": 1}` — with a read_timeout that
  long, an automatic retry on a call still legitimately in progress just
  doubles the wait instead of recovering anything.
- **A Lambda that self-invokes (async fan-out) must not reference its own
  ARN/name via a CDK token.** `self.some_fn.function_name` /
  `.function_arn` render as `Ref`/`GetAtt` back to the same resource; combined
  with CDK's automatic "function depends on its own IAM policy" edge, that's
  a real circular dependency CloudFormation rejects at deploy time (not at
  synth — `cdk synth` and `cdk diff` both looked clean). Build the ARN from
  `Aws.PARTITION`/`Aws.REGION`/`Aws.ACCOUNT_ID` plus the *literal*
  `function_name` string you already passed in instead.
- **The model can wrap valid JSON in reasoning prose despite an explicit
  "never return anything outside this JSON" instruction**, especially on a
  long, judgment-heavy input (Stage 2 on a full 12-page story produced a
  "pre-flight analysis" essay before the JSON and "reviewer notes" after
  it). Don't assume `json.loads()` on the raw response, or even a
  fenced-block-at-the-start check, is enough — extract the JSON regardless
  of what surrounds it (try whole-response parse, then any fenced
  ```` ```json ``` ```` block anywhere in the text, then a balanced
  brace-scan for the first top-level `{...}`). Repeating the "JSON only"
  instruction as the literal last line of the user message (after the input
  data, not just once in a long system prompt) measurably reduces how often
  this happens, though it doesn't eliminate it — keep the robust parsing
  regardless.
- **A worker Lambda invoked via `InvocationType="Event"` must not re-raise
  after it has already recorded a failure.** Lambda automatically retries a
  *failed* async invocation up to 2 more times by default. If the job's
  terminal state (DynamoDB row + logged traceback) is already written before
  the exception propagates, re-raising just triggers silent, wasted retries
  of a job the caller has already stopped polling for — and pollutes
  CloudWatch with confusing interleaved re-attempts of stale jobs. Catch,
  record, log, and `return` (don't re-raise) once the failure is durably
  captured.
- **Style Guide's default fidelity reproduces the reference image's whole
  scene**, not just its stroke width/color-palette style — a generated
  character came back with the reference's mountains, birds, and scattered
  leaves baked in, which background-removal then can't cleanly separate
  from the subject. Use a low `fidelity` (~0.2) for every non-background
  asset to keep it isolated on a plain backdrop; full fidelity is correct
  for backgrounds, which *should* match the reference's whole scene.
- **Neither Style Guide nor Remove Background alone produces a usable
  transparent asset** — "transparent background" in the prompt is not
  honored by either model (both return flat RGB). Every non-background
  asset needs the explicit third call to `stable-image-remove-background`,
  chained after generation, to get real alpha transparency.
- **New S3 key prefixes need an explicit CloudFront cache behavior.**
  Writing to a new prefix in an existing bucket doesn't automatically route
  through the CDN — `illustrations/*` 404'd until a behavior matching
  `book-assets/*`'s pattern was added for it.
