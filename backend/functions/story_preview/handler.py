import os

import boto3

dynamodb = boto3.resource("dynamodb")
story_templates_table = dynamodb.Table(os.environ["STORY_TEMPLATES_TABLE"])
story_template_pages_table = dynamodb.Table(os.environ["STORY_TEMPLATE_PAGES_TABLE"])
assets_table = dynamodb.Table(os.environ["ASSETS_TABLE"])
preset_cast_members_table = dynamodb.Table(os.environ["PRESET_CAST_MEMBERS_TABLE"])

CANVAS_W = 2048
CANVAS_H = 1536
PREVIEW_WIDTH_PX = 512


def lambda_handler(event, context):
    """Invoked directly (boto3 lambda.invoke / aws lambda invoke) — never
    through API Gateway. There's no consumer-facing use for this, so
    unlike every other handler in this codebase it returns a plain HTML
    string, not the {statusCode, headers, body} envelope — the caller here
    is a human opening a file in a browser, not API Gateway."""
    story_template_id = event.get("storyTemplateId")
    if not story_template_id:
        return "<p>storyTemplateId is required.</p>"

    template = story_templates_table.get_item(Key={"storyTemplateId": story_template_id}).get("Item")
    if not template:
        return f"<p>No StoryTemplate found with id {story_template_id}.</p>"

    cast_member_id = event.get("castMemberId") or _default_cast_member(template["themePackId"])
    style_id = event.get("styleId") or "cartoon"

    pages = story_template_pages_table.query(
        KeyConditionExpression="storyTemplateId = :tid",
        ExpressionAttributeValues={":tid": story_template_id},
    ).get("Items", [])
    pages.sort(key=lambda p: p["pageOrder"])

    language_code = template.get("languageCode", "en")
    pages_html = "".join(
        _render_page(page, cast_member_id, style_id, language_code) for page in pages
    )
    preview_height_px = int(PREVIEW_WIDTH_PX * CANVAS_H / CANVAS_W)

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Preview - {template.get('title', story_template_id)}</title>
<style>
  body {{ font-family: -apple-system, sans-serif; background: #FBF8F3; padding: 24px; }}
  h1 {{ font-size: 22px; margin-bottom: 4px; }}
  .meta {{ color: #7A7E85; font-size: 13px; margin-bottom: 24px; }}
  .page {{ display: flex; gap: 24px; align-items: flex-start; margin-bottom: 32px; padding-bottom: 32px; border-bottom: 1px solid #E8E3DC; }}
  .canvas {{ position: relative; width: {PREVIEW_WIDTH_PX}px; height: {preview_height_px}px; background: #fff; border: 1px solid #E8E3DC; border-radius: 8px; overflow: hidden; flex-shrink: 0; }}
  .canvas img {{ position: absolute; object-fit: contain; }}
  .text {{ flex: 1; }}
  .pageLabel {{ font-family: monospace; color: #9A9EA5; font-size: 12px; }}
  .storyText {{ font-size: 17px; line-height: 1.5; margin-top: 6px; }}
  .warning {{ color: #D94444; font-size: 13px; margin-top: 8px; }}
</style>
</head>
<body>
  <h1>{template.get('title', '(untitled)')}</h1>
  <div class="meta">
    {story_template_id} &middot; {template.get('catalogueStatus', 'unknown')} &middot;
    {template.get('developmentalFramework', '')} &middot; {template.get('languageCode', 'en')}
  </div>
  {pages_html}
</body>
</html>"""


def _default_cast_member(theme_pack_id):
    members = preset_cast_members_table.scan().get("Items", [])
    for m in members:
        if not m.get("availableThemePacks") or theme_pack_id in m["availableThemePacks"]:
            return m["castMemberId"]
    return None


def _render_page(page, cast_member_id, style_id, language_code="en"):
    text, warnings = _resolve_text(page, language_code)
    layers = _resolve_layers(page, cast_member_id, style_id)

    images_html = ""
    for layer in sorted(layers, key=lambda l: l.get("zIndex") or 0):
        t = layer.get("transform")
        if not t or not layer.get("cdnUrl"):
            continue
        left = (t["center_x"] - t["width"] / 2) / CANVAS_W * 100
        top = (t["center_y"] - t["height"] / 2) / CANVAS_H * 100
        width = t["width"] / CANVAS_W * 100
        height = t["height"] / CANVAS_H * 100
        images_html += f'<img src="{layer["cdnUrl"]}" style="left:{left}%; top:{top}%; width:{width}%; height:{height}%;">'

    warnings_html = "".join(f'<div class="warning">Missing: {w}</div>' for w in warnings)

    return f"""
  <div class="page">
    <div class="canvas">{images_html}</div>
    <div class="text">
      <div class="pageLabel">Page {page['pageOrder']}</div>
      <div class="storyText">{text}</div>
      {warnings_html}
    </div>
  </div>"""


def _resolve_text(page, language_code="en"):
    """Same substitution logic as story_instances/handler.py's
    _resolve_page, but against defaultValuesBySlot instead of a live
    StoryInstance's filledSlotValues — there's no instance here, just the
    template's own defaults."""
    text = page.get("textTemplate", "")
    warnings = []
    for slot in page.get("slots", []):
        slot_id = slot["slotId"]
        default = page.get("defaultValuesBySlot", {}).get(slot_id)
        placeholder = f"{{{{{slot_id}}}}}"
        if not default:
            warnings.append(f"slot '{slot_id}' has no default value yet — needs a producer-picked default or new art before this page is reviewable.")
            continue
        if default.get("type") == "text":
            text = text.replace(placeholder, default.get("value", ""))
        elif default.get("type") == "asset":
            asset = assets_table.get_item(Key={"assetId": default["assetId"]}).get("Item")
            text = text.replace(placeholder, _display_label(asset, language_code) if asset else "")
    return text, warnings


def _display_label(asset, language_code):
    value = asset.get("displayLabel")
    if isinstance(value, dict):
        return value.get(language_code) or value.get("en", "")
    return value or ""


def _resolve_layers(page, cast_member_id, style_id):
    layers = [{**l, "cdnUrl": _cdn_url(l.get("cdnKey"))} for l in page.get("baseLayers", [])]

    if cast_member_id:
        for asset in _cast_base_assets(cast_member_id, style_id):
            layers.append(_asset_to_layer(asset))

    for slot in page.get("slots", []):
        default = page.get("defaultValuesBySlot", {}).get(slot["slotId"])
        if default and default.get("type") == "asset":
            asset = assets_table.get_item(Key={"assetId": default["assetId"]}).get("Item")
            if asset:
                layers.append(_asset_to_layer(asset))
    return layers


def _cast_base_assets(cast_member_id, style_id):
    key = f"{cast_member_id}#{style_id}"
    result = assets_table.query(
        IndexName="byCastMemberStyle",
        KeyConditionExpression="castMemberStyleKey = :k",
        ExpressionAttributeValues={":k": key},
    )
    return [a for a in result.get("Items", []) if a.get("layerType") == "cast_base"]


def _asset_to_layer(asset):
    return {
        "transform": asset.get("transform"),
        "zIndex": asset.get("zIndexDefault"),
        "cdnUrl": _cdn_url(asset.get("cdnKey")),
    }


def _cdn_url(cdn_key):
    if not cdn_key:
        return None
    domain = os.environ.get("CDN_DOMAIN", "")
    return f"https://{domain}/{cdn_key}" if domain else None
