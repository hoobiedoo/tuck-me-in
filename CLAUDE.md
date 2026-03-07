# Tuck Me In — Project Guide

## Project Overview

"Tuck Me In" is a platform that lets family members record bedtime stories in their own voice and make them available to children on-demand through voice assistants. See `docs/design-document.md` for the full design document.

## Tech Stack

- **Backend**: Python — AWS CDK for IaC, Python Lambda functions, boto3
- **Infrastructure**: AWS serverless — API Gateway, Lambda, DynamoDB, S3, Cognito, CloudFront, SQS/SNS
- **Mobile App**: React Native or Flutter (TBD) — iOS and Android
- **Voice Integrations**: Alexa Skill (MVP), then Google Assistant, Siri/HomePod, Bixby
- **Payments**: Stripe
- **Language**: English only at launch

## Architecture Principles

- **Python-first**: All backend code is Python unless absolutely required otherwise. Prompt before using a different language.
- **Serverless-first**: Use Lambda + API Gateway for all backend logic. No EC2/ECS unless proven necessary.
- **Unified voice layer**: All voice platforms translate into a common intent schema (`PlayStory`, `ListStories`, `RequestStory`, etc.). Core logic is written once.
- **Household-based access**: Content is scoped to households. Users and children are members of a household. Voice devices are linked to a household.
- **COPPA compliant**: No data collection from children. Parental consent required. Data deletion on request.

## Key Design Decisions

- No live reading / real-time audio — pre-recorded only
- No AI text-to-speech or voice cloning — authentic human voice only
- Max story length: 1 hour (~57MB at 128kbps)
- Children can request stories; family members get push notifications to record

## Project Structure

```
tuck-me-in/
├── CLAUDE.md                          # This file
├── docs/
│   └── design-document.md            # Full project design document
├── backend/                           # AWS CDK Python project
│   ├── app.py                        # CDK app entry point
│   ├── cdk.json                      # CDK configuration
│   ├── requirements.txt              # Python dependencies
│   ├── backend/
│   │   ├── backend_stack.py          # Main CDK stack (wires all constructs)
│   │   └── constructs/
│   │       ├── auth.py               # Cognito user pool + client
│   │       ├── database.py           # DynamoDB tables + GSIs
│   │       ├── storage.py            # S3 bucket + CloudFront CDN
│   │       ├── processing.py         # SQS queues + SNS topics
│   │       └── api.py                # API Gateway + Lambda functions + permissions
│   └── functions/                     # Lambda function handlers
│       ├── households/handler.py     # CRUD for households + children
│       ├── stories/handler.py        # CRUD for stories + presigned upload URLs
│       ├── requests/handler.py       # Story request management + SNS notifications
│       ├── devices/handler.py        # Voice device linking/unlinking
│       └── audio_processor/handler.py # SQS-triggered audio processing
├── mobile/                            # React Native / Flutter mobile app (TBD)
├── voice/
│   ├── alexa/                        # Alexa Skill (Phase 1)
│   ├── google/                       # Google Assistant action (Phase 2)
│   ├── siri/                         # Siri/HomePod integration (Phase 3)
│   └── bixby/                        # Bixby capsule (Phase 3)
└── shared/                            # Shared constants, intent schemas
```

## Core Data Entities

- **Household** — top-level account, owns all content and members
- **User** — family member (parent, reader, child-proxy), authenticated via Cognito
- **Child Profile** — linked to household, has approved readers list
- **Story** — audio recording metadata, linked to reader and household, stored in S3
- **StoryRequest** — child-to-reader request with status tracking (pending/in-progress/completed/declined)
- **LinkedDevice** — voice device linked to a household

## Common Intent Schema

All voice platforms map to these intents:

| Intent | Description |
|---|---|
| `PlayStory` | Play a story by title and/or reader |
| `ListStories` | List available stories, optionally filtered by reader |
| `ResumeStory` | Resume a paused story |
| `RequestStory` | Child requests a family member record a specific story |
| `RandomStory` | Play a random story from the library |

## Development Conventions

- **Python for all backend code** — Lambda functions, CDK infrastructure, shared utilities
- Infrastructure as Code using AWS CDK (Python)
- Environment variables for all configuration — no hardcoded ARNs or secrets
- S3 audio access via CloudFront signed URLs only — never expose S3 directly
- DynamoDB tables with GSIs for access patterns (byHousehold, byReader, byRequestedReader)
- All API endpoints behind API Gateway with Cognito authorizer (except voice platform webhooks which use their own auth)

## Commands

```bash
# Backend setup
cd backend
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt  # Windows
# source .venv/bin/activate && pip install -r requirements.txt  # Linux/Mac

# CDK commands (run from backend/)
npx cdk synth          # Synthesize CloudFormation template
npx cdk diff           # Compare with deployed stack
npx cdk deploy         # Deploy to AWS (uses AWS_PROFILE=personal)
npx cdk destroy        # Tear down stack

# Mobile (placeholder)
# cd mobile && npm install && npx react-native start

# Alexa Skill (placeholder)
# cd voice/alexa && ask deploy
```

## API Endpoints

All endpoints require Cognito auth except `POST /households` (account creation).

| Method | Path | Handler | Description |
|---|---|---|---|
| POST | `/households` | households | Create household (signup) |
| GET | `/households` | households | List user's households |
| GET | `/households/{id}` | households | Get household details |
| PUT | `/households/{id}` | households | Update household |
| POST | `/households/{id}/children` | households | Add child profile |
| GET | `/households/{id}/children` | households | List children |
| POST | `/stories` | stories | Create story record |
| GET | `/stories?householdId=` | stories | List stories |
| GET | `/stories/{id}` | stories | Get story details |
| DELETE | `/stories/{id}` | stories | Archive story |
| GET | `/stories/{id}/upload-url` | stories | Get presigned S3 upload URL |
| POST | `/requests` | requests | Create story request |
| GET | `/requests?householdId=` | requests | List requests |
| GET | `/requests/{id}` | requests | Get request details |
| PUT | `/requests/{id}` | requests | Update request status |
| POST | `/devices` | devices | Link voice device |
| GET | `/devices?householdId=` | devices | List linked devices |
| DELETE | `/devices/{id}` | devices | Unlink device |

## Testing

- Unit tests for all Lambda functions (pytest)
- Integration tests for API Gateway endpoints
- Voice interaction testing via Alexa Simulator and platform-specific test tools
- COPPA compliance audit before any public release

## MVP Scope (Phase 1)

1. Mobile app: recording, library management, story requests, accounts
2. Alexa Skill: play, list, resume, request intents
3. AWS backend: Cognito, API Gateway, Lambda, S3, DynamoDB, SNS
4. Free tier + pay-per-recording via Stripe
5. Single-household support
6. English only
