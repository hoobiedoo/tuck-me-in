"""JSON Schema for the interactive story content model's Bedrock tool-use
call (compose_interactive_story / generate_interactive_story).

See docs/interactive-story-content-model.md for the full design and product
rationale. Three primitives, replacing simple {{slot}} substitution for
anything that needs to be illustrated:

  entityChoices  -- the identity registry: every choice the child can make,
                     with its options (each with a displayLabel and a
                     revealLine -- the in-voice reaction played on tap).
  presentsChoice / entityReferences on a page -- the two ways a page can
                     touch an entityChoice: introduce it, or reference an
                     earlier one with a bespoke sentence per option (never
                     a template substitution -- see textByOption below).
  branchPoints   -- bounded, convergent forks: a handful of pages that
                     differ per option, always reconverging to an identical
                     continuation and page count, never a general branching
                     tree.

Free-text personalization (a name) stays on the old, simpler
CONTROLLED_VOCAB_WITH_OVERRIDE slot mechanism -- entityChoices are for
enumerable, illustrated options, not arbitrary text.
"""

INTERACTIVE_STORY_TOOL_NAME = "emit_interactive_story"

_ENTITY_CATEGORIES = [
    "IDENTITY", "COMPANION", "OBJECT", "ABILITY",
    "DESTINATION", "PLOT_EVENT", "CELEBRATION", "KEEPSAKE",
]
_INTERACTION_TYPES = ["TAP_REVEAL", "DRAG", "MYSTERY_DOOR"]

_ENTITY_OPTION = {
    "type": "object",
    "required": ["optionId", "displayLabel", "revealLine"],
    "properties": {
        "optionId": {"type": "string"},
        "displayLabel": {"type": "string"},
        # The in-voice reaction played the instant this option is picked,
        # wherever it's picked -- authored once per option, not once per
        # (option, page). Recorded in the family member's voice like
        # everything else; never generated/synthesized at read time.
        "revealLine": {"type": "string"},
    },
}

_ENTITY_CHOICE = {
    "type": "object",
    "required": ["choiceId", "category", "displayQuestion", "interactionType", "options"],
    "properties": {
        "choiceId": {"type": "string"},
        "category": {"enum": _ENTITY_CATEGORIES},
        "displayQuestion": {"type": "string"},
        "interactionType": {"enum": _INTERACTION_TYPES},
        "options": {"type": "array", "minItems": 2, "maxItems": 4, "items": _ENTITY_OPTION},
    },
}

# A callback: NOT a placeholder substitution. One full, freshly-authored
# sentence per possible option, keyed by optionId -- the runtime does a
# lookup, never a template fill, which is what makes "still fizzing with
# soap" (a detail that only makes sense for one specific option) possible.
_ENTITY_REFERENCE = {
    "type": "object",
    "required": ["choiceId", "textByOption"],
    "properties": {
        "choiceId": {"type": "string"},
        "textByOption": {"type": "object", "additionalProperties": {"type": "string"}},
    },
}

# The old, simpler mechanism -- kept only for arbitrary free text (a name)
# that can't be an enumerable entityChoice.
_TEXT_SLOT = {
    "type": "object",
    "required": ["slotId", "slotTag", "required"],
    "properties": {
        "slotId": {"type": "string"},
        "slotTag": {"type": "string"},
        "required": {"type": "boolean"},
    },
}

_PAGE = {
    "type": "object",
    "required": ["pageOrder", "textTemplate", "sceneDescription"],
    "properties": {
        "pageOrder": {"type": "string", "pattern": "^[0-9]{4}[a-z]?$"},
        "textTemplate": {"type": "string"},
        "sceneDescription": {"type": "string"},
        # Set when this page is where an entityChoice's picker appears,
        # right after this page's text -- the chosen option's revealLine
        # plays, then the story continues.
        "presentsChoice": {"type": "string"},
        "entityReferences": {"type": "array", "items": _ENTITY_REFERENCE},
        "slots": {"type": "array", "items": _TEXT_SLOT},
        "defaultValuesBySlot": {
            "type": "object",
            "additionalProperties": {
                "type": "object",
                "required": ["type", "value"],
                "properties": {"type": {"const": "text"}, "value": {"type": "string"}},
            },
        },
    },
}

_BRANCH_POINT = {
    "type": "object",
    "required": ["choiceId", "afterPageOrder", "branchPages", "reconvergesAtPageOrder"],
    "properties": {
        "choiceId": {"type": "string"},
        # Splice branchPages in immediately after this spine pageOrder.
        "afterPageOrder": {"type": "string", "pattern": "^[0-9]{4}$"},
        # Keyed by optionId. Every branch must be the SAME LENGTH (enforced
        # in Python post-hoc, not expressible as a JSON Schema constraint) --
        # the reconvergence guarantee that keeps this bounded instead of a
        # combinatorially exploding tree.
        "branchPages": {
            "type": "object",
            "additionalProperties": {"type": "array", "items": _PAGE, "minItems": 1, "maxItems": 3},
        },
        # The next SPINE pageOrder every branch continues into, identically.
        "reconvergesAtPageOrder": {"type": "string", "pattern": "^[0-9]{4}$"},
    },
}

INTERACTIVE_STORY_SCHEMA = {
    "type": "object",
    "required": ["status"],
    "properties": {
        "status": {"enum": ["ok", "refused"]},
        "storyTemplate": {
            "type": "object",
            "required": ["title", "oneLineSummary", "developmentalFramework", "languageCode", "isQuickStoryDefault"],
            "properties": {
                "title": {"type": "string"},
                "oneLineSummary": {"type": "string"},
                "developmentalFramework": {"type": "string"},
                "languageCode": {"type": "string"},
                "isQuickStoryDefault": {"type": "boolean"},
            },
        },
        "entityChoices": {"type": "array", "minItems": 3, "maxItems": 8, "items": _ENTITY_CHOICE},
        "pages": {"type": "array", "items": _PAGE},
        "branchPoints": {"type": "array", "items": _BRANCH_POINT},
        "field": {"type": "string"},
        "reason": {"type": "string"},
    },
}
