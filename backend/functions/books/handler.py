import json
import os

import boto3

dynamodb = boto3.resource("dynamodb")
books_table = dynamodb.Table(os.environ["BOOKS_TABLE"])
book_segments_table = dynamodb.Table(os.environ["BOOK_SEGMENTS_TABLE"])


def lambda_handler(event, context):
    http_method = event["httpMethod"]
    resource = event["resource"]

    if resource == "/books" and http_method == "GET":
        return list_books(event)
    elif resource == "/books/{bookId}" and http_method == "GET":
        return get_book(event)
    elif resource == "/books/{bookId}/segments" and http_method == "GET":
        return list_segments(event)

    return response(404, {"message": "Not found"})


def list_books(event):
    """Global catalogue — every household sees the same published books.
    catalogueStatus is never a client-controlled filter: only published
    books are ever returned here."""
    result = books_table.scan(
        FilterExpression="catalogueStatus = :s",
        ExpressionAttributeValues={":s": "published"},
    )
    return response(200, result.get("Items", []))


def get_book(event):
    book_id = event["pathParameters"]["bookId"]
    result = books_table.get_item(Key={"bookId": book_id})
    item = result.get("Item")
    if not item or item.get("catalogueStatus") != "published":
        return response(404, {"message": "Book not found"})
    return response(200, item)


def list_segments(event):
    book_id = event["pathParameters"]["bookId"]
    book = books_table.get_item(Key={"bookId": book_id}).get("Item")
    if not book or book.get("catalogueStatus") != "published":
        return response(404, {"message": "Book not found"})

    result = book_segments_table.query(
        KeyConditionExpression="bookId = :bid",
        ExpressionAttributeValues={":bid": book_id},
    )
    return response(200, result.get("Items", []))


def response(status_code, body):
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
        },
        "body": json.dumps(body, default=str),
    }
