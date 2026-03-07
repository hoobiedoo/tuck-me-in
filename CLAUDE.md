# Tuck Me In — Project Guide

## Project Overview

"Tuck Me In" is a platform that lets family members record bedtime stories in their own voice and make them available to children on-demand through voice assistants. See `docs/design-document.md` for the full design document.

## Tech Stack

- **Backend**: AWS serverless — API Gateway, Lambda, DynamoDB, S3, Cognito, CloudFront, MediaConvert, SQS/SNS, Pinpoint
- **Mobile App**: React Native or Flutter (TBD) — iOS and Android
- **Voice Integrations**: Alexa Skill (MVP), then Google Assistant, Siri/HomePod, Bixby
- **Payments**: Stripe
- **Language**: English only at launch

## Architecture Principles

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
├── CLAUDE.md              # This file
├── docs/
│   └── design-document.md # Full project design document
├── backend/               # AWS Lambda functions and infrastructure
│   ├── functions/         # Lambda function handlers
│   ├── lib/               # Shared backend utilities
│   └── infra/             # IaC (CDK or SAM templates)
├── mobile/                # React Native / Flutter mobile app
├── voice/
│   ├── alexa/             # Alexa Skill definition and handlers
│   ├── google/            # Google Assistant action (Phase 2)
│   ├── siri/              # Siri/HomePod integration (Phase 3)
│   └── bixby/             # Bixby capsule (Phase 3)
└── shared/                # Shared types, constants, intent schemas
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

- Use TypeScript for Lambda functions and shared code
- Infrastructure as Code using AWS CDK (preferred) or SAM
- Environment variables for all configuration — no hardcoded ARNs or secrets
- S3 audio access via CloudFront signed URLs only — never expose S3 directly
- DynamoDB single-table design where practical; use GSIs for access patterns
- All API endpoints behind API Gateway with Cognito authorizer (except voice platform webhooks which use their own auth)

## MVP Scope (Phase 1)

1. Mobile app: recording, library management, story requests, accounts
2. Alexa Skill: play, list, resume, request intents
3. AWS backend: Cognito, API Gateway, Lambda, S3, DynamoDB, SNS/Pinpoint
4. Free tier + pay-per-recording via Stripe
5. Single-household support
6. English only

## Commands

Commands will be documented here as the project build progresses:

```bash
# Backend (placeholder)
# cd backend && npm install
# npx cdk deploy

# Mobile (placeholder)
# cd mobile && npm install
# npx react-native start

# Alexa Skill (placeholder)
# cd voice/alexa && ask deploy
```

## Testing

- Unit tests for all Lambda functions
- Integration tests for API Gateway endpoints
- Voice interaction testing via Alexa Simulator and platform-specific test tools
- COPPA compliance audit before any public release
