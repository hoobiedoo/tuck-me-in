from aws_cdk import (
    RemovalPolicy,
    aws_dynamodb as dynamodb,
)
from constructs import Construct


class DatabaseConstruct(Construct):

    def __init__(self, scope: Construct, id: str) -> None:
        super().__init__(scope, id)

        # Households table
        self.households_table = dynamodb.Table(
            self, "HouseholdsTable",
            table_name="tuck-me-in-households",
            partition_key=dynamodb.Attribute(
                name="householdId", type=dynamodb.AttributeType.STRING
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.RETAIN,
        )

        # Users table
        self.users_table = dynamodb.Table(
            self, "UsersTable",
            table_name="tuck-me-in-users",
            partition_key=dynamodb.Attribute(
                name="userId", type=dynamodb.AttributeType.STRING
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.RETAIN,
        )
        self.users_table.add_global_secondary_index(
            index_name="byHousehold",
            partition_key=dynamodb.Attribute(
                name="householdId", type=dynamodb.AttributeType.STRING
            ),
        )

        # Children table
        self.children_table = dynamodb.Table(
            self, "ChildrenTable",
            table_name="tuck-me-in-children",
            partition_key=dynamodb.Attribute(
                name="childId", type=dynamodb.AttributeType.STRING
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.RETAIN,
        )
        self.children_table.add_global_secondary_index(
            index_name="byHousehold",
            partition_key=dynamodb.Attribute(
                name="householdId", type=dynamodb.AttributeType.STRING
            ),
        )

        # Stories table
        self.stories_table = dynamodb.Table(
            self, "StoriesTable",
            table_name="tuck-me-in-stories",
            partition_key=dynamodb.Attribute(
                name="storyId", type=dynamodb.AttributeType.STRING
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.RETAIN,
        )
        self.stories_table.add_global_secondary_index(
            index_name="byHousehold",
            partition_key=dynamodb.Attribute(
                name="householdId", type=dynamodb.AttributeType.STRING
            ),
        )
        self.stories_table.add_global_secondary_index(
            index_name="byReader",
            partition_key=dynamodb.Attribute(
                name="readerId", type=dynamodb.AttributeType.STRING
            ),
        )

        # Story Requests table
        self.story_requests_table = dynamodb.Table(
            self, "StoryRequestsTable",
            table_name="tuck-me-in-story-requests",
            partition_key=dynamodb.Attribute(
                name="requestId", type=dynamodb.AttributeType.STRING
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.RETAIN,
        )
        self.story_requests_table.add_global_secondary_index(
            index_name="byHousehold",
            partition_key=dynamodb.Attribute(
                name="householdId", type=dynamodb.AttributeType.STRING
            ),
        )
        self.story_requests_table.add_global_secondary_index(
            index_name="byRequestedReader",
            partition_key=dynamodb.Attribute(
                name="requestedReaderId", type=dynamodb.AttributeType.STRING
            ),
        )

        # Linked Devices table
        self.linked_devices_table = dynamodb.Table(
            self, "LinkedDevicesTable",
            table_name="tuck-me-in-linked-devices",
            partition_key=dynamodb.Attribute(
                name="deviceId", type=dynamodb.AttributeType.STRING
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.RETAIN,
        )
        self.linked_devices_table.add_global_secondary_index(
            index_name="byHousehold",
            partition_key=dynamodb.Attribute(
                name="householdId", type=dynamodb.AttributeType.STRING
            ),
        )

        # Auto-Release Grants table — sparse: a row only exists when a
        # contributor is trusted to auto-release to a specific child.
        self.auto_release_grants_table = dynamodb.Table(
            self, "AutoReleaseGrantsTable",
            table_name="tuck-me-in-auto-release-grants",
            partition_key=dynamodb.Attribute(
                name="contributorId", type=dynamodb.AttributeType.STRING
            ),
            sort_key=dynamodb.Attribute(
                name="childId", type=dynamodb.AttributeType.STRING
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.RETAIN,
        )
        self.auto_release_grants_table.add_global_secondary_index(
            index_name="byChild",
            partition_key=dynamodb.Attribute(
                name="childId", type=dynamodb.AttributeType.STRING
            ),
        )

        # Pending Publish Notifications table — batches "contributor
        # published" events into one digest per household every few minutes.
        self.pending_publish_notifications_table = dynamodb.Table(
            self, "PendingPublishNotificationsTable",
            table_name="tuck-me-in-pending-publish-notifications",
            partition_key=dynamodb.Attribute(
                name="householdId", type=dynamodb.AttributeType.STRING
            ),
            sort_key=dynamodb.Attribute(
                name="windowStartedAt", type=dynamodb.AttributeType.STRING
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.RETAIN,
            time_to_live_attribute="ttl",
        )

        # Books table — global catalogue, not household-scoped. No GSI:
        # the catalogue is small and ops-curated, listed via scan.
        self.books_table = dynamodb.Table(
            self, "BooksTable",
            table_name="tuck-me-in-books",
            partition_key=dynamodb.Attribute(
                name="bookId", type=dynamodb.AttributeType.STRING
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.RETAIN,
        )

        # Book Segments table — sort key is a zero-padded reading-order
        # index, giving native reading-order queries. GSI byCfi backs
        # re-import diffing (looking up a segment by its stable CFI).
        self.book_segments_table = dynamodb.Table(
            self, "BookSegmentsTable",
            table_name="tuck-me-in-book-segments",
            partition_key=dynamodb.Attribute(
                name="bookId", type=dynamodb.AttributeType.STRING
            ),
            sort_key=dynamodb.Attribute(
                name="segmentOrder", type=dynamodb.AttributeType.STRING
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.RETAIN,
        )
        self.book_segments_table.add_global_secondary_index(
            index_name="byCfi",
            partition_key=dynamodb.Attribute(
                name="bookId", type=dynamodb.AttributeType.STRING
            ),
            sort_key=dynamodb.Attribute(
                name="cfi", type=dynamodb.AttributeType.STRING
            ),
        )

        # Book Imports table — diff staging + audit trail for re-imports of
        # an already-published book. A draft book's re-upload overwrites
        # its segment set directly and never touches this table.
        self.book_imports_table = dynamodb.Table(
            self, "BookImportsTable",
            table_name="tuck-me-in-book-imports",
            partition_key=dynamodb.Attribute(
                name="bookId", type=dynamodb.AttributeType.STRING
            ),
            sort_key=dynamodb.Attribute(
                name="importVersion", type=dynamodb.AttributeType.NUMBER
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.RETAIN,
        )

        # Takes table — append-only log of every recording attempt for a
        # segment. GSI bySegmentSlot (bookId#cfi#contributorId, takeNumber)
        # gives native "all takes for this segment, in order" / "get the
        # latest" queries. A take's own row is never edited by anyone else's
        # write — only its own status fields change.
        self.takes_table = dynamodb.Table(
            self, "TakesTable",
            table_name="tuck-me-in-takes",
            partition_key=dynamodb.Attribute(
                name="takeId", type=dynamodb.AttributeType.STRING
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.RETAIN,
        )
        self.takes_table.add_global_secondary_index(
            index_name="bySegmentSlot",
            partition_key=dynamodb.Attribute(
                name="segmentSlotKey", type=dynamodb.AttributeType.STRING
            ),
            sort_key=dynamodb.Attribute(
                name="takeNumber", type=dynamodb.AttributeType.NUMBER
            ),
        )

        # Segment Recordings table — the current-state pointer per
        # (book, segment, contributor). currentTakeNumber is the single
        # source of truth the take-versioning race guard checks against.
        self.segment_recordings_table = dynamodb.Table(
            self, "SegmentRecordingsTable",
            table_name="tuck-me-in-segment-recordings",
            partition_key=dynamodb.Attribute(
                name="bookId", type=dynamodb.AttributeType.STRING
            ),
            sort_key=dynamodb.Attribute(
                name="contributorSegmentKey", type=dynamodb.AttributeType.STRING
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.RETAIN,
        )

        # --- Mad Libs Wizard ---
        # Two groups below: ThemePacks/Assets/StoryTemplates/PresetCastMembers
        # are Tier 2 production output — the wizard only ever reads them.
        # StoryInstances and everything under it are owned by the wizard.

        # Theme Packs table — global catalogue, not household-scoped, same
        # shape as BooksTable. Small and ops-curated, listed via scan.
        self.theme_packs_table = dynamodb.Table(
            self, "ThemePacksTable",
            table_name="tuck-me-in-theme-packs",
            partition_key=dynamodb.Attribute(
                name="themePackId", type=dynamodb.AttributeType.STRING
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.RETAIN,
        )

        # Assets table — every illustrated piece Tier 2 produces. The
        # byPackStyleSlot GSI is the wizard's one real query: given the
        # active (themePackId, styleId, slotTag), return only the Assets
        # that actually exist for it — no cross-pack fallback is possible
        # because nothing outside that partition is ever queried.
        self.assets_table = dynamodb.Table(
            self, "AssetsTable",
            table_name="tuck-me-in-assets",
            partition_key=dynamodb.Attribute(
                name="assetId", type=dynamodb.AttributeType.STRING
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.RETAIN,
        )
        self.assets_table.add_global_secondary_index(
            index_name="byPackStyleSlot",
            partition_key=dynamodb.Attribute(
                name="packStyleSlotKey", type=dynamodb.AttributeType.STRING
            ),
        )
        # Cast pieces (layerType cast_base/cast_expression) aren't
        # themePack-scoped — the same Preset Cast member can appear across
        # multiple packs — so they're looked up by castMemberId + styleId
        # instead. Only cast-piece rows populate this attribute.
        self.assets_table.add_global_secondary_index(
            index_name="byCastMemberStyle",
            partition_key=dynamodb.Attribute(
                name="castMemberStyleKey", type=dynamodb.AttributeType.STRING
            ),
        )
        # Supports "every slotTag this ThemePack has, across every style" —
        # needed to build EXISTING_SLOT_VOCABULARY for the content
        # generation pipeline. byPackStyleSlot can't answer this alone since
        # it requires a specific styleId already known.
        self.assets_table.add_global_secondary_index(
            index_name="byThemePack",
            partition_key=dynamodb.Attribute(
                name="themePackId", type=dynamodb.AttributeType.STRING
            ),
        )

        # Story Templates table — one row per template; byThemePack lets the
        # wizard list a pack's templates (e.g. to find its Quick Story
        # default) without a scan.
        self.story_templates_table = dynamodb.Table(
            self, "StoryTemplatesTable",
            table_name="tuck-me-in-story-templates",
            partition_key=dynamodb.Attribute(
                name="storyTemplateId", type=dynamodb.AttributeType.STRING
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.RETAIN,
        )
        self.story_templates_table.add_global_secondary_index(
            index_name="byThemePack",
            partition_key=dynamodb.Attribute(
                name="themePackId", type=dynamodb.AttributeType.STRING
            ),
        )

        # Story Template Pages table — sort key is a zero-padded page-order
        # index, same convention as BookSegments, for native reading-order
        # queries. Each page carries its text template and typed slot defs.
        self.story_template_pages_table = dynamodb.Table(
            self, "StoryTemplatePagesTable",
            table_name="tuck-me-in-story-template-pages",
            partition_key=dynamodb.Attribute(
                name="storyTemplateId", type=dynamodb.AttributeType.STRING
            ),
            sort_key=dynamodb.Attribute(
                name="pageOrder", type=dynamodb.AttributeType.STRING
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.RETAIN,
        )

        # Preset Cast Members table — the illustrated-cast roster. Small,
        # curated, listed via scan like ThemePacks. A member's actual visual
        # pieces (base body + swappable expressions) are just Assets rows
        # tagged with this castMemberId — no separate vector-guide schema.
        self.preset_cast_members_table = dynamodb.Table(
            self, "PresetCastMembersTable",
            table_name="tuck-me-in-preset-cast-members",
            partition_key=dynamodb.Attribute(
                name="castMemberId", type=dynamodb.AttributeType.STRING
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.RETAIN,
        )

        # Developmental Frameworks table — narrative-arc guidance and
        # content-production wizard questions, keyed by frameworkId. Small,
        # curated, listed via scan like ThemePacks/PresetCastMembers. Single
        # source of truth for: Stage 1 generation prompt input, the (not yet
        # built) production wizard's questions, and the parent-facing
        # mobile picker — replacing what used to be hardcoded independently
        # in three places.
        self.developmental_frameworks_table = dynamodb.Table(
            self, "DevelopmentalFrameworksTable",
            table_name="tuck-me-in-developmental-frameworks",
            partition_key=dynamodb.Attribute(
                name="frameworkId", type=dynamodb.AttributeType.STRING
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.RETAIN,
        )

        self.story_production_jobs_table = dynamodb.Table(
            self, "StoryProductionJobsTable",
            table_name="tuck-me-in-story-production-jobs",
            partition_key=dynamodb.Attribute(name="jobId", type=dynamodb.AttributeType.STRING),
            time_to_live_attribute="expiresAt",
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.RETAIN,
        )

        # Story Instances table — a household's assembled Mad Libs story.
        # contributorStatus/assignments follow Stories' exact lifecycle
        # pattern. narratorId is set once, on the first recorded take.
        self.story_instances_table = dynamodb.Table(
            self, "StoryInstancesTable",
            table_name="tuck-me-in-story-instances",
            partition_key=dynamodb.Attribute(
                name="storyInstanceId", type=dynamodb.AttributeType.STRING
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.RETAIN,
        )
        self.story_instances_table.add_global_secondary_index(
            index_name="byHousehold",
            partition_key=dynamodb.Attribute(
                name="householdId", type=dynamodb.AttributeType.STRING
            ),
        )

        # Story Instance Pages table — same zero-padded-order convention as
        # BookSegments/StoryTemplatePages. filledSlotValues is the
        # authoritative Mad Libs state; resolvedText and compositionSpec are
        # deterministically derived from it on every write, never edited
        # independently.
        self.story_instance_pages_table = dynamodb.Table(
            self, "StoryInstancePagesTable",
            table_name="tuck-me-in-story-instance-pages",
            partition_key=dynamodb.Attribute(
                name="storyInstanceId", type=dynamodb.AttributeType.STRING
            ),
            sort_key=dynamodb.Attribute(
                name="pageOrder", type=dynamodb.AttributeType.STRING
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.RETAIN,
        )

        # Story Instance Takes table — mirrors Takes exactly, keyed by page
        # instead of EPUB cfi. No contributor segmentation: a StoryInstance
        # has exactly one narrator, so bySegmentSlot only needs
        # storyInstanceId#pageOrder.
        self.story_instance_takes_table = dynamodb.Table(
            self, "StoryInstanceTakesTable",
            table_name="tuck-me-in-story-instance-takes",
            partition_key=dynamodb.Attribute(
                name="takeId", type=dynamodb.AttributeType.STRING
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.RETAIN,
        )
        self.story_instance_takes_table.add_global_secondary_index(
            index_name="bySegmentSlot",
            partition_key=dynamodb.Attribute(
                name="segmentSlotKey", type=dynamodb.AttributeType.STRING
            ),
            sort_key=dynamodb.Attribute(
                name="takeNumber", type=dynamodb.AttributeType.NUMBER
            ),
        )

        # Story Instance Segment Recordings table — mirrors
        # SegmentRecordings, keyed by pageOrder instead of a
        # contributor#cfi composite (again, one narrator per instance).
        # Editing a page's filledSlotValues while this row has a
        # currentTakeId supersedes that take in the same write — see
        # story_instances/handler.py.
        self.story_instance_segment_recordings_table = dynamodb.Table(
            self, "StoryInstanceSegmentRecordingsTable",
            table_name="tuck-me-in-story-instance-segment-recordings",
            partition_key=dynamodb.Attribute(
                name="storyInstanceId", type=dynamodb.AttributeType.STRING
            ),
            sort_key=dynamodb.Attribute(
                name="pageOrder", type=dynamodb.AttributeType.STRING
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.RETAIN,
        )
