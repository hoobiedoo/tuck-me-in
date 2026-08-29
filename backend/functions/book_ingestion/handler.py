import hashlib
import io
import json
import os
import posixpath
import urllib.parse
import zipfile
from datetime import datetime

import boto3
import ebooklib
from ebooklib import epub
from lxml import etree
from lxml import html as lxml_html

dynamodb = boto3.resource("dynamodb")
books_table = dynamodb.Table(os.environ["BOOKS_TABLE"])
book_segments_table = dynamodb.Table(os.environ["BOOK_SEGMENTS_TABLE"])
book_imports_table = dynamodb.Table(os.environ["BOOK_IMPORTS_TABLE"])
s3_client = boto3.client("s3")

CATALOGUE_ASSETS_BUCKET = os.environ["CATALOGUE_ASSETS_BUCKET"]
CDN_DOMAIN = os.environ.get("CDN_DOMAIN", "")

CONTAINER_NS = "urn:oasis:names:tc:opendocument:xmlns:container"
OPF_NS = "http://www.idpf.org/2007/opf"
EPUB_NS = "http://www.idpf.org/2007/ops"

NARRATABLE_TAGS = {"p", "li", "blockquote", "h1", "h2", "h3", "h4", "h5", "h6", "td", "th"}
SEGMENT_TYPE_BY_TAG = {
    "p": "paragraph", "li": "list_item", "blockquote": "blockquote",
    "h1": "heading", "h2": "heading", "h3": "heading",
    "h4": "heading", "h5": "heading", "h6": "heading",
    "td": "table_cell", "th": "table_cell",
}
SKIP_EPUB_TYPES = {"pagebreak", "footnote", "noteref"}


def lambda_handler(event, context):
    """SQS-triggered by S3 ObjectCreated notifications on the (ops-only,
    private) catalogue source bucket. Each SQS record body is a raw S3 event
    notification, which may itself batch multiple object records."""
    failed_items = []

    for record in event["Records"]:
        try:
            s3_event = json.loads(record["body"])
            for s3_record in s3_event.get("Records", []):
                bucket = s3_record["s3"]["bucket"]["name"]
                key = urllib.parse.unquote_plus(s3_record["s3"]["object"]["key"])
                process_book(bucket, key)
        except Exception as e:
            print(f"Failed to process ingestion event: {e}")
            failed_items.append({"itemIdentifier": record["messageId"]})

    return {"batchItemFailures": failed_items}


def process_book(bucket, key):
    if not key.endswith(".epub"):
        return
    book_id = key[: -len(".epub")]

    file_bytes = s3_client.get_object(Bucket=bucket, Key=key)["Body"].read()
    source_hash = hashlib.sha256(file_bytes).hexdigest()

    existing = books_table.get_item(Key={"bookId": book_id}).get("Item")
    now = datetime.utcnow().isoformat()

    if existing and existing.get("sourceFileHash") == source_hash:
        print(f"Book {book_id}: identical re-upload (hash unchanged), skipping.")
        return

    zf = zipfile.ZipFile(io.BytesIO(file_bytes))

    if "META-INF/encryption.xml" in zf.namelist():
        _save_book(book_id, existing, key, source_hash, now,
                   ingestionStatus="failed",
                   lastError="DRM-protected epub cannot be ingested.")
        return

    try:
        opf_path = _opf_path(zf)
        opf_root = etree.fromstring(zf.read(opf_path))
        layout = _detect_layout(opf_root)
    except Exception as e:
        _save_book(book_id, existing, key, source_hash, now,
                   ingestionStatus="failed",
                   lastError=f"Failed to read package metadata: {e}")
        return

    if _rootfile_count(zf) > 1:
        print(f"Book {book_id}: multiple renditions found in container.xml, using the first rootfile.")

    if layout == "fixed-layout":
        _save_book(book_id, existing, key, source_hash, now,
                   layout=layout, ingestionStatus="fixed_layout_manual_pending")
        return

    try:
        book = epub.read_epub(io.BytesIO(file_bytes))
    except Exception as e:
        _save_book(book_id, existing, key, source_hash, now,
                   ingestionStatus="failed",
                   lastError=f"Failed to open epub package: {e}")
        return

    segments, any_low_confidence = _segment_book(book, book_id, zf, opf_path)
    cover_key, cover_url = _extract_cover(book, opf_root, book_id)
    toc = _extract_toc(book)

    was_published = bool(existing and existing.get("catalogueStatus") == "published")

    if was_published:
        _stage_reimport_diff(book_id, existing, segments, source_hash, now)
        print(f"Book {book_id}: re-import of a published book staged for review, live content untouched.")
        return

    # First-time ingestion, or a re-upload of a book still in draft/rejected —
    # nothing depends on the current CFIs yet, so overwrite outright.
    _replace_live_segments(book_id, segments)

    _save_book(
        book_id, existing, key, source_hash, now,
        layout=layout,
        ingestionStatus="ready_for_review",
        catalogueStatus=(existing or {}).get("catalogueStatus", "draft"),
        segmentationConfidence="low" if any_low_confidence else "high",
        spineItemCount=len({s["spineIndex"] for s in segments}) if segments else 0,
        segmentCount=len(segments),
        tableOfContents=toc,
        coverAssetKey=cover_key,
        coverImageUrl=cover_url,
    )


# --- Package-level parsing (independent of ebooklib, for the checks we need
# to be certain about: DRM presence, rendition layout, rootfile count) ---

def _opf_path(zf):
    container = etree.fromstring(zf.read("META-INF/container.xml"))
    rootfile = container.find(f".//{{{CONTAINER_NS}}}rootfile")
    return rootfile.get("full-path")


def _rootfile_count(zf):
    container = etree.fromstring(zf.read("META-INF/container.xml"))
    return len(container.findall(f".//{{{CONTAINER_NS}}}rootfile"))


def _detect_layout(opf_root):
    for meta in opf_root.iter(f"{{{OPF_NS}}}meta"):
        if meta.get("property") == "rendition:layout" and (meta.text or "").strip() == "pre-paginated":
            return "fixed-layout"
    return "reflowable"


# --- Spine walk + segmentation ---

def _ordered_spine_items(book):
    items = []
    for idref, _linear in book.spine:
        item = book.get_item_with_id(idref)
        if item is not None:
            items.append(item)
    return items


def _segment_book(book, book_id, zf, opf_path):
    """Reads each spine document's bytes directly from the zip, keyed by
    href resolved against the OPF's directory — NOT via ebooklib's
    EpubHtml.get_content(), which re-parses and re-serializes document
    content internally and has been observed to silently drop bare text
    sitting directly in <body> before any child element (exactly the
    no-real-<p>-tags case the fallback path below exists to handle)."""
    segments = []
    any_low_confidence = False
    order = 0
    opf_dir = posixpath.dirname(opf_path)

    for spine_index, item in enumerate(_ordered_spine_items(book)):
        href = item.get_name()
        full_path = posixpath.normpath(posixpath.join(opf_dir, href))
        try:
            raw_content = zf.read(full_path)
        except KeyError:
            print(f"Spine item {href} not found in the archive at {full_path} — skipping this chapter.")
            continue

        try:
            # HTML5-style parsing, not XML recover mode: real-world epub
            # markup's most common defect is missing closes on tags with
            # well-known implicit-close rules (a new <p> auto-closing an
            # open one, an <li> auto-closing the previous <li>, ...).
            # XMLParser(recover=True) has no concept of implicit closing —
            # verified against a sample with an unclosed <p> mid-chapter,
            # it folded the entire rest of the document inside that one
            # <p>. lxml.html's HTML5-style parser closes it correctly.
            tree = lxml_html.document_fromstring(raw_content)
        except Exception as e:
            print(f"Failed to parse spine item {href}: {e} — skipping this chapter, continuing with the rest.")
            continue
        if tree is None:
            print(f"Spine item {href} was unrecoverable — skipping this chapter.")
            continue

        doc_segments, low_confidence = _extract_segments(tree, spine_index, href, book, book_id)
        any_low_confidence = any_low_confidence or low_confidence

        for seg in doc_segments:
            seg["segmentOrder"] = f"{order:05d}"
            order += 1
            segments.append(seg)

    return segments, any_low_confidence


def _local_tag(el):
    tag = el.tag
    if not isinstance(tag, str):
        return None
    return tag.split("}")[-1] if "}" in tag else tag


def _epub_type_skip_reason(el):
    node = el
    while node is not None:
        etype = node.get(f"{{{EPUB_NS}}}type") or node.get("epub:type")
        if etype:
            for token in etype.split():
                if token in SKIP_EPUB_TYPES:
                    return token
        node = node.getparent()
    return None


def _find_body(root):
    for tag_variant in (f"{{{'http://www.w3.org/1999/xhtml'}}}body", "body"):
        found = root.find(f".//{tag_variant}")
        if found is not None:
            return found
    return root


def _extract_text(el):
    return "".join(el.itertext()).strip()


def _spine_cfi_step(spine_index):
    return 2 * (spine_index + 1)


def _element_cfi_path(element, doc_root):
    steps = []
    node = element
    while node is not None and node is not doc_root:
        parent = node.getparent()
        if parent is None:
            break
        element_children = [c for c in parent if isinstance(c.tag, str)]
        index = element_children.index(node) + 1
        steps.append(str(2 * index))
        node = parent
    steps.reverse()
    return "/" + "/".join(steps)


def generate_cfi(spine_index, element, doc_root):
    return f"epubcfi(/6/{_spine_cfi_step(spine_index)}!{_element_cfi_path(element, doc_root)})"


def _is_nested_in_narratable(el, body):
    """Only the outermost narratable ancestor becomes a segment — avoids
    double-counting e.g. a <p> nested inside an <li>."""
    parent = el.getparent()
    while parent is not None and parent is not body:
        if _local_tag(parent) in NARRATABLE_TAGS:
            return True
        parent = parent.getparent()
    return False


def _resolve_href(doc_href, src):
    return posixpath.normpath(posixpath.join(posixpath.dirname(doc_href), src))


def _extract_segments(root, spine_index, doc_href, book, book_id):
    body = _find_body(root)
    all_elements = list(body.iter())
    has_block_tag = any(_local_tag(el) in NARRATABLE_TAGS for el in all_elements)

    if not has_block_tag:
        fallback_segments = _fallback_br_split(root, body, spine_index, doc_href, book, book_id)
        # Only actual text-splitting-heuristic segments should mark the
        # book low-confidence -- a wrapper page that resolved to nothing
        # but a clean image segment (or nothing at all) isn't a
        # segmentation problem. Confirmed against real epubs: Gutenberg's
        # toolchain emits image-only wrapper pages routinely, and without
        # this check every book would be flagged low-confidence regardless
        # of actual segmentation quality.
        any_text_fallback = any(s["segmentType"] == "fallback_block" for s in fallback_segments)
        return fallback_segments, any_text_fallback

    segments = []
    for el in all_elements:
        tag = _local_tag(el)

        if tag in ("img", "image"):
            seg = _image_segment(el, spine_index, doc_href, root, book, book_id)
            if seg:
                segments.append(seg)
            continue

        if tag not in NARRATABLE_TAGS or _is_nested_in_narratable(el, body):
            continue

        text = _extract_text(el)
        if not text:
            continue

        skip_reason = _epub_type_skip_reason(el)
        segments.append({
            "cfi": generate_cfi(spine_index, el, root),
            "spineIndex": spine_index,
            "spineItemHref": doc_href,
            "segmentType": SEGMENT_TYPE_BY_TAG[tag],
            "text": text,
            "textHash": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "confidence": "high",
            "narratable": skip_reason is None,
            "skipReason": skip_reason,
            "assetKey": None,
            "altText": None,
            "status": "active",
        })

    return segments, False


def _fallback_br_split(root, body, spine_index, doc_href, book, book_id):
    """No real block tags in this chapter — split on runs of 2+ <br>, but
    stay image-aware while doing it: an image-only wrapper page (no <p>,
    just an illustration) is a real, common pattern — confirmed against a
    real epub where every single illustration lives on its own such page —
    and without detecting images here they'd be silently absent from the
    segment stream entirely, which is worse than the text-splitting
    heuristic this function exists to flag for review. There's no
    individual element to point a CFI at for the text pieces, so their
    path is synthesized from split order rather than a real element
    position; flagged low-confidence so a curator reviews the boundaries
    before the book can be published. Image segments found along the way
    use their real element-based CFI and aren't part of that flag."""
    segments = []
    buffer = []
    consecutive_br = 0
    order = 0

    def flush():
        nonlocal order
        text = "".join(buffer).strip()
        buffer.clear()
        if text:
            cfi = f"epubcfi(/6/{_spine_cfi_step(spine_index)}!/4/{2 * (order + 1)})"
            segments.append({
                "cfi": cfi,
                "spineIndex": spine_index,
                "spineItemHref": doc_href,
                "segmentType": "fallback_block",
                "text": text,
                "textHash": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                "confidence": "low",
                "narratable": True,
                "skipReason": None,
                "assetKey": None,
                "altText": None,
                "status": "active",
            })
            order += 1

    def walk(node):
        nonlocal consecutive_br
        if node.text:
            buffer.append(node.text)
            consecutive_br = 0
        for child in node:
            tag = _local_tag(child)
            if tag == "br":
                consecutive_br += 1
                if consecutive_br >= 2:
                    flush()
                    consecutive_br = 0
            elif tag in ("img", "image"):
                flush()
                consecutive_br = 0
                seg = _image_segment(child, spine_index, doc_href, root, book, book_id)
                if seg:
                    segments.append(seg)
            else:
                consecutive_br = 0
                walk(child)
            if child.tail:
                buffer.append(child.tail)
                consecutive_br = 0

    walk(body)
    flush()
    return segments


def _image_segment(img_el, spine_index, doc_href, root, book, book_id):
    # HTML <img src=""> and SVG <image xlink:href=""> (the latter confirmed
    # against real epubs -- Gutenberg's cover-wrapper pages use it, and
    # lxml.html leaves the attribute name as the literal "xlink:href"
    # string rather than resolving it as a namespaced attribute).
    src = img_el.get("src") or img_el.get("xlink:href") or img_el.get("href")
    if not src:
        return None

    asset_key = None
    try:
        href = _resolve_href(doc_href, src)
        item = book.get_item_with_href(href)
        if item is not None:
            content = item.get_content()
            asset_hash = hashlib.sha256(content).hexdigest()
            ext = href.rsplit(".", 1)[-1]
            asset_key = f"book-assets/{book_id}/{asset_hash}.{ext}"
            s3_client.put_object(
                Bucket=CATALOGUE_ASSETS_BUCKET, Key=asset_key, Body=content,
                ContentType=item.media_type or "image/jpeg",
            )
        else:
            print(f"Image referenced at {doc_href} ({src}) not found in manifest — keeping the segment, asset unresolved.")
    except Exception as e:
        print(f"Failed to resolve/upload image {src} referenced from {doc_href}: {e} — keeping the segment, asset unresolved.")

    return {
        "cfi": generate_cfi(spine_index, img_el, root),
        "spineIndex": spine_index,
        "spineItemHref": doc_href,
        "segmentType": "image",
        "text": None,
        "textHash": None,
        "confidence": "high",
        "narratable": False,
        "skipReason": None,
        "assetKey": asset_key,
        "altText": img_el.get("alt", ""),
        "status": "active",
    }


# --- Cover, uploaded to the shared, content-addressed catalogue asset store ---

def _extract_cover(book, opf_root, book_id):
    cover_item = None
    for item in book.get_items_of_type(ebooklib.ITEM_COVER):
        cover_item = item
        break

    if cover_item is None:
        # EPUB2 convention: <meta name="cover" content="item-id"/>. ebooklib
        # stores every generic OPF <meta> tag under the literal key "meta",
        # with the actual name/content pair living in the attributes dict —
        # NOT keyed by the meta tag's own "name" attribute as get_metadata's
        # signature might suggest. Confirmed against a real EPUB2 file.
        try:
            for _value, attrs in book.get_metadata("OPF", "meta"):
                if attrs.get("name") == "cover":
                    cover_item = book.get_item_with_id(attrs.get("content"))
                    break
        except Exception:
            cover_item = None  # No cover declared under either convention — left null, not guessed.

    if cover_item is None:
        return None, None

    content = cover_item.get_content()
    asset_hash = hashlib.sha256(content).hexdigest()
    ext = cover_item.get_name().rsplit(".", 1)[-1]
    key = f"book-assets/{book_id}/{asset_hash}.{ext}"

    s3_client.put_object(
        Bucket=CATALOGUE_ASSETS_BUCKET, Key=key, Body=content,
        ContentType=cover_item.media_type or "image/jpeg",
    )
    url = f"https://{CDN_DOMAIN}/{key}" if CDN_DOMAIN else None
    return key, url


# --- Table of contents ---

def _extract_toc(book):
    entries = []

    def walk(nodes):
        for node in nodes:
            if isinstance(node, tuple):
                link, children = node
                if getattr(link, "href", None) and getattr(link, "title", None):
                    entries.append({"title": link.title, "href": link.href})
                walk(children)
            elif getattr(node, "href", None) and getattr(node, "title", None):
                entries.append({"title": node.title, "href": node.href})

    walk(book.toc)
    return entries


# --- Persistence ---

def _save_book(book_id, existing, source_key, source_hash, now, **fields):
    item = dict(existing or {})
    item.update({
        "bookId": book_id,
        "sourceFileKey": source_key,
        "sourceFileHash": source_hash,
        "updatedAt": now,
        "createdAt": item.get("createdAt", now),
        "importVersion": item.get("importVersion", 0),
    })
    item.update(fields)
    books_table.put_item(Item=item)


def _replace_live_segments(book_id, segments):
    existing_keys = [
        {"bookId": r["bookId"], "segmentOrder": r["segmentOrder"]}
        for r in book_segments_table.query(
            KeyConditionExpression="bookId = :bid",
            ExpressionAttributeValues={":bid": book_id},
            ProjectionExpression="bookId, segmentOrder",
        ).get("Items", [])
    ]
    with book_segments_table.batch_writer() as writer:
        for key in existing_keys:
            writer.delete_item(Key=key)
        for seg in segments:
            writer.put_item(Item={"bookId": book_id, "importVersionIntroduced": 1, **seg})


# --- Re-import diffing (published books only) ---

def _stage_reimport_diff(book_id, existing_book, new_segments, new_hash, now):
    live_segments = book_segments_table.query(
        KeyConditionExpression="bookId = :bid",
        ExpressionAttributeValues={":bid": book_id},
    ).get("Items", [])

    live_by_cfi = {s["cfi"]: s for s in live_segments}
    new_by_cfi = {s["cfi"]: s for s in new_segments}
    live_hashes = {s["textHash"] for s in live_segments if s.get("textHash")}
    new_hashes = {s["textHash"] for s in new_segments if s.get("textHash")}

    added = removed = changed = unchanged = would_orphan = 0

    for cfi, new_seg in new_by_cfi.items():
        old_seg = live_by_cfi.get(cfi)
        if old_seg is None:
            if new_seg.get("textHash") in live_hashes:
                unchanged += 1  # same text, shifted CFI
            else:
                added += 1
        elif old_seg.get("textHash") == new_seg.get("textHash"):
            unchanged += 1
        else:
            changed += 1

    for cfi, old_seg in live_by_cfi.items():
        if cfi not in new_by_cfi and old_seg.get("textHash") not in new_hashes:
            removed += 1
            would_orphan += 1

    next_version = int(existing_book.get("importVersion", 1)) + 1

    book_imports_table.put_item(Item={
        "bookId": book_id,
        "importVersion": next_version,
        "sourceFileHash": new_hash,
        "diffSummary": {
            "added": added, "removed": removed, "changed": changed,
            "unchanged": unchanged, "wouldOrphan": would_orphan,
        },
        "stagedSegments": new_segments,
        "status": "pending_review",
        "triggeredAt": now,
    })


def apply_import(event, context):
    """Manually invoked by an operator (not wired to any trigger) once a
    staged re-import's diffSummary has been reviewed and accepted."""
    book_id = event["bookId"]
    import_version = event["importVersion"]

    staged = book_imports_table.get_item(
        Key={"bookId": book_id, "importVersion": import_version}
    ).get("Item")
    if not staged or staged.get("status") != "pending_review":
        raise ValueError(f"No pending_review import {import_version} for book {book_id}")

    _replace_live_segments(book_id, staged["stagedSegments"])

    now = datetime.utcnow().isoformat()
    books_table.update_item(
        Key={"bookId": book_id},
        UpdateExpression="SET importVersion = :v, sourceFileHash = :h, frozenAt = :f, updatedAt = :u",
        ExpressionAttributeValues={
            ":v": import_version, ":h": staged["sourceFileHash"],
            ":f": now, ":u": now,
        },
    )
    book_imports_table.update_item(
        Key={"bookId": book_id, "importVersion": import_version},
        UpdateExpression="SET #s = :s",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={":s": "applied"},
    )


def set_catalogue_status(event, context):
    """Manually invoked by a curator to move a book between draft, published,
    and rejected. No API surface — ingestion and curation are ops-only."""
    book_id = event["bookId"]
    new_status = event["catalogueStatus"]
    if new_status not in ("draft", "published", "rejected"):
        raise ValueError(f"Invalid catalogueStatus: {new_status}")

    now = datetime.utcnow().isoformat()
    update_expr = "SET catalogueStatus = :s, updatedAt = :u"
    values = {":s": new_status, ":u": now}

    if new_status == "published":
        update_expr += ", frozenAt = :f, importVersion = :v"
        values[":f"] = now
        values[":v"] = 1

    books_table.update_item(
        Key={"bookId": book_id},
        UpdateExpression=update_expr,
        ExpressionAttributeValues=values,
    )
