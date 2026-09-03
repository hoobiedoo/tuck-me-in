# Interactive Story Content Model

**Status: Stage 1 schema + prompt implemented and validated live; not yet wired into the rest of the pipeline.** This document is the living source of truth for this design — update it as the design evolves, don't let it drift out of sync with chat history.

## Implementation status

- `backend/functions/story_production/interactive_story_schema.py` — the JSON Schema (Bedrock tool-use) for the shape below.
- `backend/functions/story_production/prompts/stage1-interactive-story-v1.txt` — the Stage 1 prompt.
- `compose_interactive_story` / `generate_interactive_story` actions in `handler.py` — additive and parallel to `compose`/`generate_story`. Nothing else in the pipeline (`write_draft`, Stage 2, `story_instances`) consumes this output yet — that's the next phase.
- `_validate_interactive_story_output` / `_validate_interactive_page` — deterministic cross-reference validation: every `entityChoice` must be presented exactly once and (unless it drives a `branchPoint`) referenced again later; `textByOption` keys must exactly match a choice's declared `optionId`s; every branch within a `branchPoint` must have the same page count; dash-checking extends to every text field (`revealLine`, callback sentences, branch pages).
- Live-tested directly against Bedrock (bypassing the job queue, ~35-45s per call): first attempt was correctly refused by the validator (the model introduced a choice and never paid it off — confirms the validator catches real drift, not just theoretical cases); second attempt produced a fully valid story with genuinely bespoke, character-voice-specific callback text per option (e.g. differentiated per-species reactions for a companion choice) — not templated substitution.

## Why this exists

The Story Studio pipeline (Stages 0-3, see `docs/tier2-ai-assisted-production-prompts.md` and `docs/tier3-story-generation-prompt.md`) currently produces stories personalized through simple Mad-Libs-style `{{slot}}` substitution: one placeholder, one chosen value, inserted verbatim. That model can't support the product experience described below, which needs choices that get *referenced* with freshly-written prose later in the story, and choices that change *what happens* rather than just which noun is used.

## The product vision

The target experience is **agency, not authorship**. The child should never feel like they're filling out a form before the story starts. The story is already great; the child gets to make the important, funny, magical decisions — and those decisions should visibly come back later ("that was when Mia remembered the rubber chicken"), which is what makes the child feel "I did that."

### The eight choice categories

| Choice | Example | Why kids care |
|---|---|---|
| Who am I? | astronaut / dragon / raccoon / wizard | Identity |
| Who comes with me? | robot / puppy / monster / grandma | Relationship |
| Where are we going? | moon / candy jungle / pirate island | Fantasy |
| What ridiculous thing do we bring? | giant spoon / bubble wand / underwear cannon | Humor |
| What special ability do we have? | super bounce / invisibility / talking to animals | Power |
| What goes wrong? | bridge disappears / dragon wakes up / moon rolls away | Suspense |
| What should we do? | sneak / ask for help / build something / be silly | Agency |
| How should we celebrate? | dance party / pancakes / fireworks / cuddle pile | Payoff |

Explicitly *not* asked: "pick an adjective/verb/color/noun" — those are authoring mechanics, not experiences.

### Key interaction mechanics

- **Choices happen inside the story, not as a form up front.** Maybe 2-3 up front (world, hero, companion), the rest surface naturally as the story reaches that beat.
- **Tablet-native interaction, not menus** — tap-to-reveal with a personality reaction (the dragon says "Huh?", the robot says "BEEP. ADVENTURE MODE ACTIVATED."), drag-and-drop (toss items into a backpack), mystery doors (pick a silhouette, don't know what's behind it).
- **Choices with no wrong answer** — "sing / offer a snack / dance-challenge" all resolve the scene; the choice is about personality, not correctness.
- **Delayed consequences** — a chosen power (super sneeze) is set up early, forgotten, then pays off later ("he remembered something very important... ACHOOO! Door flies open").
- **Adventure Tray** — a persistent visual inventory of the child's choices so far, especially important for pre-readers since it makes story state visual.
- **Keepsake ending** — the child picks one souvenir from the adventure at the end; it becomes part of a persistent collection ("bookshelf") across stories, driving repeat play.

### A known tension to resolve later

Tuck Me In's core product constraint (`CLAUDE.md`) is **pre-recorded human voice only — no AI narration, no live reading**. This vision's delight mechanics (character reaction lines playing immediately on tap) lean on something closer to live narrated stingers. Needs reconciling before the app-layer work starts: either these become pre-recorded human-voiced clips per option, or the mechanic adapts to the audio model. Not resolved yet.

## Technical design: three content primitives

The existing flat `pages: [{ pageOrder, textTemplate, slots, ... }]` array with `{{slot}}` substitution can't express callbacks (bespoke prose referencing an earlier choice) or branching (different plot events per choice). Three primitives cover the vision without building a general branching engine:

1. **Entity Choice** — child picks once, from N options; produces a persistent trackable identity (icon, display label, illustrated states). The surrounding plot does *not* change based on which option — same pages, same events, just this identity threaded through. Covers: who am I, companion, ridiculous item, special ability, destination, celebration, keepsake.
2. **Reference** — a later point in the spine where an Entity Choice gets a freshly-authored callback sentence, not a placeholder substitution. Stage 1 (an LLM) writes one bespoke sentence per option, keyed by `optionId`, in a single generation pass — since the author is an LLM, not a human, writing every (option × callback point) combination is cheap in tokens, not cheap in labor, which is why bespoke-per-option beats generic templating here.
3. **Branch Point** — child picks once, from N options, and the *next few pages* genuinely differ per option, then reconverge to an identical continuation and page count. Reserved for the rare cases (like "what goes wrong") where the actual plot event changes — most choices should be Entity-Choice-shaped, not this. Branches must reconverge within a small fixed page budget and produce the same page count across options, so illustration/background planning stays bounded (no combinatorial explosion).

### Worked example shape

```jsonc
{
  "status": "ok",
  "storyTemplate": { "title": "...", "oneLineSummary": "...", "developmentalFramework": "...", "languageCode": "en", "isQuickStoryDefault": false },

  // Identity registry for every choice in the story -- not sequencing, just definitions.
  "entityChoices": [
    {
      "choiceId": "companion",
      "category": "COMPANION",              // -> which illustration asset category this needs
      "displayQuestion": "Who comes with me?",
      "interactionType": "TAP_REVEAL",       // vs "DRAG", "MYSTERY_DOOR" -- tells the app which widget to render
      "options": [
        { "optionId": "octopus", "displayLabel": "Octopus", "revealLine": "An OCTOPUS?! In the middle of the forest?!" },
        { "optionId": "dragon",  "displayLabel": "Dragon",  "revealLine": "A dragon! Its eyes blink open, slow and sleepy." }
      ]
    },
    {
      "choiceId": "ridiculous_item",
      "category": "OBJECT",
      "displayQuestion": "What ridiculous thing do we bring?",
      "interactionType": "DRAG",
      "options": [
        { "optionId": "rubber_chicken", "displayLabel": "Rubber Chicken", "revealLine": "Bawk?" },
        { "optionId": "bubble_wand",    "displayLabel": "Bubble Wand",    "revealLine": "Fwoosh! Bubbles everywhere." }
      ]
    },
    {
      "choiceId": "what_goes_wrong",
      "category": "PLOT_EVENT",              // drives a branchPoint, not just a reference
      "displayQuestion": "Uh-oh! What do you think happened?",
      "interactionType": "MYSTERY_DOOR",
      "options": [
        { "optionId": "bridge_gone", "displayLabel": "The bridge disappeared!" },
        { "optionId": "dragon_woke", "displayLabel": "The dragon woke up!" }
      ]
    }
  ],

  "pages": [
    {
      "pageOrder": "0001",
      "kind": "SPINE",
      "textTemplate": "Oliver packed his bag for the forest, but he didn't want to go alone.",
      "sceneDescription": "Oliver standing by an open door, forest visible beyond",
      "presentsChoice": "companion"          // after this page's text, the app shows the picker;
                                              // the chosen option's revealLine plays before continuing
    },
    {
      "pageOrder": "0002",
      "kind": "SPINE",
      "textTemplate": "He grabbed one more thing before heading out.",
      "presentsChoice": "ridiculous_item"
    },
    {
      "pageOrder": "0003",
      "kind": "SPINE",
      "textTemplate": "Oliver and his friend walked deep into the forest until the path narrowed."
      // plain spine page -- no choice, no reference, just narrative
    },
    {
      "pageOrder": "0004",
      "kind": "BRANCH_POINT",
      "branchPoint": {
        "choiceId": "what_goes_wrong",
        // each branch is its own short page sequence, same LENGTH across
        // branches by construction, so illustration/backgrounds stay bounded
        "branchPages": {
          "bridge_gone": [{ "pageOrder": "0004a", "textTemplate": "The old rope bridge across the river was simply... gone.", "sceneDescription": "riverbank, no bridge, water rushing below" }],
          "dragon_woke": [{ "pageOrder": "0004b", "textTemplate": "A low rumble shook the ground -- the sleeping dragon was waking up.", "sceneDescription": "a dragon stirring in a rocky clearing" }]
        },
        "reconvergesAtPageOrder": "0005"
      }
    },
    {
      "pageOrder": "0005",
      "kind": "SPINE",
      // identical regardless of which branch was taken -- the reconvergence guarantee
      "textTemplate": "Oliver thought for a moment. He knew just what to do.",
      "entityReferences": [{
        "choiceId": "ridiculous_item",
        "textByOption": {
          "rubber_chicken": "He reached into his bag and pulled out the rubber chicken. Somehow, it always came in handy.",
          "bubble_wand": "He reached into his bag and pulled out the bubble wand, still faintly fizzing."
        }
      }]
    }
  ]
}
```

Field notes:
- **`revealLine`** lives on the option, not per-page — the same reaction every time that option is picked anywhere, authored once per option.
- **`presentsChoice` / `entityReferences` / `branchPoint`** are the three touchpoints a page can have with the choice system. Most pages have none and are just spine narrative.
- **Branch page IDs (`0004a`/`0004b`)** are an authoring-time disambiguator only — the reading app just shows sequential page numbers for whichever branch got spliced in for that reader.

## How this connects to what's already been fixed this session

Debugging the current (non-branching) illustration pipeline surfaced a foundational gap that this design inherits and must account for: **`story_template_pages.baseLayers` is written once, hardcoded to `[]`, at `write_draft` time, and nothing in the codebase ever populates it from generated illustration assets.** Even the protagonist currently shows one static pose on every page (`_cast_base_layers` only pulls the `cast_base` master, never the per-page `cast_expression` variants). This needs fixing regardless of the interactive-content-model work, and the two efforts should be sequenced together: background + protagonist wiring first (no dependency on this new content model), then Entity Choice illustration (which depends on this design's shape).

Confirmed direction from that discussion, relevant here: **background stays fixed per page; only characters/objects swap.** And personalized character art should be **pre-generated for every option at catalog-production time**, not generated live on a customer's first pick — a live Bedrock call in the middle of a drag-and-drop interaction is the wrong place to risk the failure modes (throttling, bad types, wrong-subject bleed-through) this session spent so much time fixing.

## Voice recording and the resolution step

Story Studio (producer-facing) only ever produces the *template* — every `entityChoice` option and every `branchPoint` branch, fully illustrated (per the pre-generation decision above). It does not resolve a story to one path, and it has no voice-recording concerns at all — that's a deliberately separate, later, family/customer-facing flow.

Traced the existing recording system (`story_instance_takes/handler.py`) to check how it should extend. Key finding: **personalization already resolves to one fixed reading *before* recording begins, today** — `begin_take` refuses to start a take until `story_instance_pages.resolvedText` exists for that page, and a narrator's take set is frozen at "release." A family member always records one linear, already-decided performance, never multiple branches.

This settles the biggest open question from the interactive model: it does **not** require pre-recording every branch/option to support live child-driven choice during playback, because there is no live playback branching in this product (`CLAUDE.md`: pre-recorded only, no live reading). The child's "tap to choose" moment has to happen at a **resolution step** — turning a template's `entityChoices`/`branchPoint`s plus one concrete pick per choice into a single flat page sequence, the same shape `story_instance_pages_table` already expects — which happens *before* the family member ever starts recording. The family member then records that one resolved reading exactly like today's flow, unchanged. The "discovery" feeling the vision wants is preserved because the *child* (whoever is present at resolution time) doesn't know the outcome until that tap, even though the family member recording it afterward already does — which if anything makes for a warmer recording (genuine excitement, not a cold read).

**New work implied**: a resolution step/component that flattens a template + a set of choice picks into a linear, recordable page sequence. **Not new work**: the takes/segment-recording/alignment infrastructure itself, which already assumes exactly this shape.

**Open sub-question**: should per-option reveal lines ("BEEP. ADVENTURE MODE ACTIVATED.") be recorded in the family member's voice too (consistent warmth throughout), or handled as a separate reusable sound-design element? Leaning toward family-voice by default since that's the product's core differentiator, not decided yet.

## Open questions / not yet decided

- **Adventure Tray representation** — needs its own icon/sticker rendering per option, distinct from the in-story illustrated pose. Not yet modeled in the schema above.
- **Mystery-door silhouette state** — a pre-reveal art state distinct from the revealed option art. Not yet modeled.
- **Producer-preview default** — Story Studio's existing "preview the story before any real customer has chosen anything" QA flow needs a defined default `optionId` per `entityChoice` for preview rendering. Not yet decided how that default is chosen or stored.
- **Validator redesign** — this session added deterministic Stage 1 validators (em/en dash rejection, `slotId` naming, `newSlotTagsNeedingArt` scoping) against the old flat-slot model. These need re-deriving against `entityChoices`/`branchPoint`/`entityReferences`, not simply deleted.
- **Keepsake/collection data model** — cross-story persistent state (the "bookshelf"), not yet designed at all.
- **Audio tension** — see above, unresolved.

## Status / next steps

Stage 1 (schema + prompt + validation) is implemented and live-validated, additive and non-breaking to the existing pipeline (see Implementation status above). Not yet wired into: `write_draft` (needs to persist `entityChoices`/`branchPoints` to the catalogue instead of assuming flat pages), Stage 2 (needs the multi-option-per-choice illustration extension discussed earlier), or `story_instances` (needs the resolution step that flattens a template + one pick per choice into a linear, recordable page sequence — see Voice recording section above). Next step: pick one of those three and extend it.
