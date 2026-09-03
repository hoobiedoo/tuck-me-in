"""JSON Schema for Stage 1 (generate_story)'s Bedrock tool-use call,
mirroring the OUTPUT FORMAT section of stage1-story-slots-v1.txt.

Enforces every field's type and required-ness at generation time. It
CANNOT enforce the one rule that actually broke live (a slot's slotId must
appear verbatim as a {{...}} placeholder in a *different* field,
textTemplate) -- JSON Schema has no keyword for a value constraint that
spans two sibling fields. _validate_page in handler.py still checks that
cross-field invariant after the call returns; this schema only removes the
type/shape mistakes tool use can actually prevent.
"""

_SLOT = {
    "type": "object",
    "required": ["slotId", "slotType", "slotTag", "required", "isNewSlotTag"],
    "properties": {
        "slotId": {"type": "string"},
        "slotType": {"enum": ["CONTROLLED_VOCAB", "CONTROLLED_VOCAB_WITH_OVERRIDE"]},
        "slotTag": {"type": "string"},
        "layerType": {"type": "string"},
        "required": {"type": "boolean"},
        "isNewSlotTag": {"type": "boolean"},
    },
}

_DEFAULT_VALUE = {
    "type": "object",
    "oneOf": [
        {
            "required": ["type", "displayLabelHint"],
            "properties": {
                "type": {"const": "asset"},
                "displayLabelHint": {"type": "string"},
            },
        },
        {
            "required": ["type", "value"],
            "properties": {
                "type": {"const": "text"},
                "value": {"type": "string"},
            },
        },
    ],
}

_PAGE = {
    "type": "object",
    "required": ["pageOrder", "textTemplate", "sceneDescription", "slots", "defaultValuesBySlot"],
    "properties": {
        "pageOrder": {"type": "string", "pattern": "^[0-9]{4}$"},
        "textTemplate": {"type": "string"},
        "sceneDescription": {"type": "string"},
        "slots": {"type": "array", "items": _SLOT},
        "defaultValuesBySlot": {"type": "object", "additionalProperties": _DEFAULT_VALUE},
    },
}

_STORY_TEMPLATE = {
    "type": "object",
    "required": ["title", "oneLineSummary", "developmentalFramework", "languageCode", "isQuickStoryDefault"],
    "properties": {
        "title": {"type": "string"},
        "oneLineSummary": {"type": "string"},
        "developmentalFramework": {"type": "string"},
        "languageCode": {"type": "string"},
        "isQuickStoryDefault": {"type": "boolean"},
    },
}

_NEW_SLOT_TAG_NEEDING_ART = {
    "type": "object",
    "required": ["slotTag", "layerType", "proposedDisplayLabels"],
    "properties": {
        "slotTag": {"type": "string"},
        "layerType": {"type": "string"},
        "proposedDisplayLabels": {"type": "array", "items": {"type": "string"}},
    },
}

STORY_SPEC_TOOL_NAME = "emit_story_template"

STORY_SPEC_SCHEMA = {
    "type": "object",
    "required": ["status"],
    "properties": {
        "status": {"enum": ["ok", "refused"]},
        "storyTemplate": _STORY_TEMPLATE,
        "pages": {"type": "array", "items": _PAGE},
        "newNameSuggestionsProposed": {
            "type": "object",
            "additionalProperties": {"type": "array", "items": {"type": "string"}},
        },
        "newSlotTagsNeedingArt": {"type": "array", "items": _NEW_SLOT_TAG_NEEDING_ART},
        "field": {"type": "string"},
        "reason": {"type": "string"},
    },
}
