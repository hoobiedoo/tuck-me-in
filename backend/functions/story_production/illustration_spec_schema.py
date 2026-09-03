"""JSON Schema for Stage 2 (generate_illustration_spec)'s Bedrock tool-use
call, mirroring the OUTPUT FORMAT section of stage2-illustration-spec-v2.txt.

Passed as a tool inputSchema on the Converse API call so the model's output
is constrained at generation time -- wrong types (a stringified number) and
out-of-enum values (an unlisted glow color) become something the model
can't produce, instead of something _validate_illustration_spec has to catch
after a ~100s call has already run.
"""

from procedural_effects import GLOW_COLOR_HEX

_DEPTH_GROUPS = ["Foreground", "Midground", "Background"]

_TRANSFORM = {
    "type": "object",
    "required": ["center_x", "center_y", "width", "height", "rotation_degrees"],
    "properties": {
        "center_x": {"type": "number"},
        "center_y": {"type": "number"},
        "width": {"type": "number"},
        "height": {"type": "number"},
        "rotation_degrees": {"type": "number"},
    },
}

_CHARACTER_BIBLE = {
    "type": "object",
    "required": [
        "species", "approximateAge", "headShape", "earShape", "muzzle",
        "eyeConstruction", "bodyProportions", "silhouette", "clothing",
        "accessories", "outline", "palette",
    ],
    "properties": {
        "species": {"type": "string"},
        "approximateAge": {"type": "string"},
        "headShape": {"type": "string"},
        "earShape": {"type": "string"},
        "muzzle": {"type": "string"},
        "eyeConstruction": {"type": "string"},
        "bodyProportions": {"type": "string"},
        "silhouette": {"type": "string"},
        "clothing": {"type": "string"},
        "accessories": {"type": "string"},
        "outline": {"type": "string"},
        "palette": {"type": "array", "items": {"type": "string"}},
    },
}

_NEW_IDENTITY = {
    "type": "object",
    "required": [
        "assetKind", "identityKey", "kind", "layerType", "characterBible",
        "masterPrompt", "forPageOrders", "depthGroup", "zIndexDefault", "transform",
    ],
    "properties": {
        "assetKind": {"const": "NEW_IDENTITY"},
        "identityKey": {"type": "string"},
        "kind": {"enum": ["PROTAGONIST", "STORY_CHARACTER"]},
        "layerType": {"enum": ["cast_base", "prop_character"]},
        "characterBible": _CHARACTER_BIBLE,
        "masterPrompt": {"type": "string"},
        "forPageOrders": {"type": "array", "items": {"type": "string"}},
        "depthGroup": {"enum": _DEPTH_GROUPS},
        "zIndexDefault": {"type": "integer"},
        "transform": _TRANSFORM,
    },
}

_VARIANT_OF_IDENTITY = {
    "type": "object",
    "required": [
        "assetKind", "identityKey", "variantKey", "layerType", "mutation",
        "forPageOrders", "depthGroup", "zIndexDefault", "transform",
    ],
    "properties": {
        "assetKind": {"const": "VARIANT_OF_IDENTITY"},
        "identityKey": {"type": "string"},
        "variantKey": {"type": "string"},
        "layerType": {"enum": ["cast_expression", "prop_character"]},
        "mutation": {
            "type": "object",
            "properties": {
                "expression": {
                    "type": "object",
                    "properties": {
                        "eyes": {"type": "string"},
                        "mouth": {"type": "string"},
                        "brows": {"type": "string"},
                    },
                },
                "pose": {"type": "string"},
                "gaze": {"type": "string"},
                "view": {"type": "string"},
            },
        },
        "forPageOrders": {"type": "array", "items": {"type": "string"}},
        "depthGroup": {"enum": _DEPTH_GROUPS},
        "zIndexDefault": {"type": "integer"},
        "transform": _TRANSFORM,
    },
}

_BACKGROUND = {
    "type": "object",
    "required": [
        "assetKind", "identityKey", "layerType", "scene", "forPageOrders",
        "depthGroup", "zIndexDefault", "transform",
    ],
    "properties": {
        "assetKind": {"const": "BACKGROUND"},
        "identityKey": {"type": "string"},
        "layerType": {"const": "background"},
        "scene": {
            "type": "object",
            "required": [
                "groundShape", "treeMasses", "skyType", "starCount",
                "horizonLine", "otherElements", "negativeSpaceNote",
            ],
            "properties": {
                "groundShape": {"type": "string"},
                "treeMasses": {"type": "string"},
                "skyType": {"type": "string"},
                "starCount": {"type": "string"},
                "horizonLine": {"type": "string"},
                "otherElements": {"type": "string"},
                "negativeSpaceNote": {"type": "string"},
            },
        },
        "forPageOrders": {"type": "array", "items": {"type": "string"}},
        "depthGroup": {"const": "Background"},
        "zIndexDefault": {"type": "integer"},
        "transform": _TRANSFORM,
    },
}

_PROCEDURAL_EFFECT = {
    "type": "object",
    "required": [
        "assetKind", "identityKey", "layerType", "effectType", "color",
        "radius", "falloff", "opacity", "forPageOrders", "depthGroup",
        "zIndexDefault", "transform",
    ],
    "properties": {
        "assetKind": {"const": "PROCEDURAL_EFFECT"},
        "identityKey": {"type": "string"},
        "layerType": {"const": "prop_light"},
        "effectType": {"const": "radial_glow"},
        # Constrained to the deterministic renderer's actual palette (or a
        # literal hex) so an out-of-list color name can't reach
        # procedural_effects.py at all -- this is the schema-level fix for
        # the "Unknown glow color 'pale silver'" failure.
        "color": {
            "oneOf": [
                {"enum": sorted(GLOW_COLOR_HEX)},
                {"type": "string", "pattern": "^#[0-9A-Fa-f]{6}$"},
            ]
        },
        "radius": {"type": "number"},
        "falloff": {"type": "number"},
        "opacity": {"type": "number"},
        "forPageOrders": {"type": "array", "items": {"type": "string"}},
        "depthGroup": {"enum": ["Foreground", "Midground"]},
        "zIndexDefault": {"type": "integer"},
        "transform": _TRANSFORM,
    },
}

_STATIC_PROP = {
    "type": "object",
    "required": [
        "assetKind", "identityKey", "layerType", "physicalPrompt",
        "forPageOrders", "depthGroup", "zIndexDefault", "transform",
    ],
    "properties": {
        "assetKind": {"const": "STATIC_PROP"},
        "identityKey": {"type": "string"},
        "layerType": {"const": "prop_character"},
        "physicalPrompt": {"type": "string"},
        "forPageOrders": {"type": "array", "items": {"type": "string"}},
        "depthGroup": {"enum": _DEPTH_GROUPS},
        "zIndexDefault": {"type": "integer"},
        "transform": _TRANSFORM,
    },
}

ILLUSTRATION_SPEC_TOOL_NAME = "emit_illustration_spec"

ILLUSTRATION_SPEC_SCHEMA = {
    "type": "object",
    "required": ["status"],
    "properties": {
        "status": {"enum": ["ok", "refused"]},
        "assets": {
            "type": "array",
            "items": {
                "oneOf": [
                    _NEW_IDENTITY, _VARIANT_OF_IDENTITY, _BACKGROUND,
                    _PROCEDURAL_EFFECT, _STATIC_PROP,
                ],
            },
        },
        "pageOrder": {"type": ["string", "null"]},
        "identityKey": {"type": ["string", "null"]},
        "reason": {"type": "string"},
    },
}
