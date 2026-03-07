# Project Design Document: "Tuck Me In" — Remote Bedtime Story Platform

## Problem Statement

Parents and family members are frequently away from their children at bedtime due to work travel, military deployment, separation, or other circumstances. Children miss the comfort and bonding of having a loved one read them a bedtime story. There is no seamless solution that lets a child simply ask their voice assistant — "Ask Mom to read me Goodnight Moon" — and hear that story in their family member's actual voice, pre-recorded and ready to play.

## Vision

Build a platform that allows family members to **record bedtime stories** in their own voice, store them securely, and make them available on-demand to their child through **any major voice assistant** (Alexa, Google Assistant, Siri/HomePod, Samsung Bixby). The child's experience should be as simple as a single voice command.

---

## Core Requirements

### 1. Story Recording & Management (Family Member Experience)

- **Mobile app** (iOS/Android) for recording stories
- Guided recording flow: select a book title (or enter custom), record chapter-by-chapter or full story, review, and publish
- Audio editing basics: trim silence, re-record segments, normalize volume
- Library management: view recorded stories, archive, delete
- Ability to **assign stories** to one or more children/households
- Support for multiple family members per household (mom, dad, grandma, uncle, etc.)
- **Maximum story length: 1 hour** per recording

### 2. Story Request Feature (Child-to-Parent Notifications)

Children (or a supervising parent on their behalf) can **request a specific story** be recorded by a family member. The workflow:

1. Child says: *"Alexa, ask Tuck Me In to request Daddy read The Cat in the Hat"*
   — or a parent submits a request via the mobile app on the child's behalf
2. The named family member receives a **push notification** in the mobile app
3. The notification includes the requested book title and which child asked
4. The family member can tap the notification to go directly into the recording flow
5. Once recorded and published, the child is notified (via the app or next voice interaction) that their story is ready
6. Requests are tracked in the app with statuses: pending, in-progress, completed, declined

### 3. Child Playback Experience (Voice Assistant Integration)

- Child (or supervising parent) says something like:
  - *"Hey Google, ask Tuck Me In to play Daddy reading The Velveteen Rabbit"*
  - *"Alexa, tell Tuck Me In to play Grandma's story"*
  - *"Alexa, ask Tuck Me In what stories are available"*
  - *"Alexa, ask Tuck Me In to request Mommy read Goodnight Moon"*
- Voice assistant should support:
  - Listing available stories by family member
  - Playing a specific story by title and/or reader
  - Resume, pause, and restart controls
  - "Read me anything" — random selection from available library
  - Requesting a story from a family member (triggers notification)
- Household linking: the voice device is linked to a child's account/household

### 4. User Accounts & Security

- **Household-based account model**: one account per household, multiple family members and children as sub-profiles
- Family members authenticate via the mobile app (email/password, social login, MFA)
- Voice devices are linked to a household during setup (device linking flow)
- Content is private by default — only linked household members can access recordings
- COPPA compliance is mandatory (children under 13 are end users)
- Audio content encrypted at rest and in transit
- Parental controls: parents approve which family members can publish stories to their child

### 5. Voice Assistant Integration Strategy

**Recommended approach: Build a single backend API and create platform-specific skill/action wrappers.**

| Platform | Integration Type | Notes |
|---|---|---|
| **Amazon Alexa** | Alexa Skill (Custom Skill) | Largest smart speaker install base. Use AudioPlayer interface for long-form audio. SMAPI for publishing. |
| **Google Assistant** | Actions on Google / Conversational Actions | Use Media Response for audio playback. Note: Google has shifted toward App Actions — evaluate current state. |
| **Apple Siri / HomePod** | SiriKit + App Intents (iOS 16+) | More limited for third-party audio. Consider AirPlay fallback or Shortcuts integration. HomePod support via Apple Music API or custom audio streaming may require creative workarounds. |
| **Samsung Bixby** | Bixby Capsule | Smaller market share but straightforward capsule development. |

**Recommended architecture**: A **unified Voice Interaction Layer** that normalizes intents across all platforms:

```
[Alexa Skill]  ─┐
[Google Action] ─┤──> [API Gateway] ──> [Intent Router] ──> [Story Service]
[Siri Shortcut] ─┤                                          ├── [Auth Service]
[Bixby Capsule] ─┘                                          ├── [Audio Service]
                                                             ├── [User Service]
                                                             └── [Request Service]
```

Each voice platform adapter translates platform-specific request formats into a **common intent schema** (e.g., `PlayStory`, `ListStories`, `IdentifyReader`, `RequestStory`), so the core logic is written once.

### 6. Monetization Model

| Tier | Price | Includes |
|---|---|---|
| **Free** | $0 | 1 recorded story (up to 1 hour), 1 household link, basic audio |
| **Storyteller** | $X per recording | Pay-per-story, up to 1 hour each, stored indefinitely |
| **Monthly Plan** | $Y/month | Up to N stories/month, audio enhancement tools, multiple households |
| **Annual Plan** | $Z/year (discount) | Everything in Monthly + priority support, extended storage, gift features |

Additional revenue opportunities to consider:
- **Gift recordings**: Grandparent buys a "story pack" as a gift
- **Licensed book integrations**: Partner with publishers for read-along text/illustrations in the app
- **Premium audio tools**: Background music, sound effects, voice enhancement filters
- **Seasonal promotions**: Holiday story bundles

### 7. AWS Backend Architecture

```
┌─────────────────────────────────────────────────────────┐
│                      AWS Cloud                          │
│                                                         │
│  ┌──────────────┐    ┌──────────────┐                   │
│  │ CloudFront   │    │ API Gateway  │<── Voice Skills   │
│  │ (Audio CDN)  │    │ (REST/WS)    │<── Mobile App     │
│  └──────┬───────┘    └──────┬───────┘                   │
│         │                   │                           │
│         │            ┌──────▼───────┐                   │
│         │            │   Lambda     │  (Intent routing, │
│         │            │   Functions  │   business logic)  │
│         │            └──────┬───────┘                   │
│         │                   │                           │
│  ┌──────▼───────┐    ┌──────▼───────┐  ┌────────────┐  │
│  │ S3           │    │ DynamoDB     │  │ Cognito    │  │
│  │ (Audio Store)│    │ (Metadata,   │  │ (Auth,     │  │
│  │              │    │  Households,  │  │  Users,    │  │
│  │              │    │  Stories)     │  │  MFA)      │  │
│  └──────────────┘    └──────────────┘  └────────────┘  │
│                                                         │
│  ┌──────────────┐    ┌──────────────┐  ┌────────────┐  │
│  │ MediaConvert │    │ SQS/SNS      │  │ CloudWatch │  │
│  │ (Audio       │    │ (Async jobs, │  │ (Logging,  │  │
│  │  processing) │    │  push notif) │  │  Metrics)  │  │
│  └──────────────┘    └──────────────┘  └────────────┘  │
│                                                         │
│  ┌──────────────┐    ┌──────────────┐  ┌────────────┐  │
│  │ Stripe       │    │ WAF / Shield │  │ Pinpoint / │  │
│  │ (Payments    │    │ (Security)   │  │ SNS Mobile │  │
│  │  via Lambda) │    │              │  │ (Push      │  │
│  └──────────────┘    └──────────────┘  │  Notifs)   │  │
│                                        └────────────┘  │
└─────────────────────────────────────────────────────────┘
```

**Key AWS service choices:**

| Concern | Service | Rationale |
|---|---|---|
| Auth | **Cognito** | Built-in user pools, MFA, social login, COPPA-friendly config |
| API | **API Gateway + Lambda** | Serverless, scales to zero, pay-per-use — ideal for early stage |
| Audio storage | **S3** with lifecycle policies | Durable, cheap, integrates with CloudFront for low-latency streaming. 1-hour max at ~128kbps = ~57MB per story. |
| Audio delivery | **CloudFront** | Signed URLs for secure, fast audio streaming to voice devices |
| Audio processing | **MediaConvert** or **Lambda + FFmpeg layer** | Normalize audio, convert formats, trim silence |
| Metadata | **DynamoDB** | Fast lookups by household, reader, title; scales seamlessly |
| Async work | **SQS + Lambda** | Audio processing jobs, notification delivery |
| Push notifications | **Pinpoint** or **SNS Mobile Push** | Deliver story request notifications to family members' devices |
| Payments | **Stripe** (external) via Lambda | Industry standard, handles subscriptions and one-time payments |
| Monitoring | **CloudWatch + X-Ray** | Distributed tracing across Lambda functions |

### 8. Data Model (Core Entities)

```
Household
  ├── householdId (PK)
  ├── name
  ├── plan (free | storyteller | monthly | annual)
  └── createdAt

User (family member)
  ├── userId (PK)
  ├── householdId (FK)
  ├── role (parent | reader | child-proxy)
  ├── displayName
  ├── deviceToken (for push notifications)
  └── cognitoSub

Child Profile
  ├── childId (PK)
  ├── householdId (FK)
  ├── name
  └── approvedReaders[] (userIds)

Story
  ├── storyId (PK)
  ├── householdId (GSI)
  ├── readerId (GSI)
  ├── title
  ├── audioKey (S3 reference)
  ├── durationSeconds (max 3600)
  ├── status (processing | ready | archived)
  └── createdAt

StoryRequest
  ├── requestId (PK)
  ├── householdId (GSI)
  ├── childId (FK)
  ├── requestedReaderId (FK, GSI)
  ├── bookTitle
  ├── status (pending | in-progress | completed | declined)
  ├── resultingStoryId (FK, nullable)
  ├── createdAt
  └── updatedAt

LinkedDevice
  ├── deviceId (PK)
  ├── householdId (FK)
  ├── platform (alexa | google | siri | bixby)
  └── linkedAt
```

### 9. Key Non-Functional Requirements

- **Latency**: Audio playback must begin within 2 seconds of voice command
- **Availability**: 99.9% uptime for playback path (it's bedtime — no retries with a sleepy child)
- **Storage limits**: Maximum 1 hour per recording (~57MB at 128kbps). Enforce at upload time.
- **COPPA compliance**: No data collection from children, parental consent flows, data deletion on request
- **Content moderation**: Consider whether to scan/flag audio content (abuse prevention)
- **Multi-region**: Start in us-east-1, design for future expansion (CloudFront handles edge delivery)
- **Offline consideration**: Mobile app should cache recordings locally for playback without voice assistant
- **Language**: English only at launch. Architecture should not preclude future multi-language support.

### 10. Design Decisions

| Question | Decision | Rationale |
|---|---|---|
| Live reading support? | **No** | MVP focuses on pre-recorded stories. Avoids real-time audio complexity (WebRTC, scheduling, availability). Can be revisited post-launch. |
| AI text-to-speech / voice cloning? | **No** | Product value is the authentic human voice of a loved one. Voice cloning raises ethical and legal concerns. Keep the experience genuine. |
| Maximum story length? | **1 hour** | Covers the vast majority of children's books. Limits storage costs (~57MB/story at 128kbps). Enforced at recording time in the mobile app. |
| Multi-language support? | **Not at launch** | English only for MVP. Architecture uses string externalization and locale-aware design to support future internationalization without rework. |
| Child story requests? | **Yes** | Children can request a specific story from a family member. The request triggers a push notification to the family member's mobile app. Requests are tracked with status (pending/in-progress/completed/declined). |

### 11. Suggested MVP Scope (Phase 1)

1. Mobile app (React Native or Flutter) with recording, library management, story requests, and account management
2. Alexa Skill (largest market) with play, list, resume, and request intents
3. AWS serverless backend (Cognito, API Gateway, Lambda, S3, DynamoDB, SNS/Pinpoint)
4. Free tier + pay-per-recording monetization only
5. Single-household support
6. Story request notifications (child requests -> parent push notification -> guided recording)
7. English only

### 12. Future Phases (Post-MVP)

- **Phase 2**: Google Assistant integration, monthly/annual subscription tiers, multiple household linking
- **Phase 3**: Apple Siri/HomePod and Samsung Bixby integration, premium audio tools (background music, sound effects)
- **Phase 4**: Multi-language support, gift recording features, publisher partnerships
- **Evaluate**: Live reading, offline voice-device playback, analytics dashboard for parents
