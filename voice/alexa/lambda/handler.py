import logging

from ask_sdk_core.skill_builder import SkillBuilder
from ask_sdk_core.dispatch_components import (
    AbstractRequestHandler,
    AbstractExceptionHandler,
)
from ask_sdk_core.utils import is_intent_name, is_request_type
from ask_sdk_model.interfaces.audioplayer import (
    PlayDirective,
    PlayBehavior,
    AudioItem,
    Stream,
    StopDirective,
)

from utils import (
    get_household_id_for_device,
    get_stories_for_household,
    get_story_by_title,
    get_random_story,
    get_audio_url,
    get_reader_display_name,
    create_story_request,
)

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

NO_DEVICE_LINKED = (
    "It looks like this device isn't linked to a Tuck Me In household yet. "
    "Please use the Tuck Me In app to link this device."
)


def get_household_or_fail(handler_input):
    """Get the household ID for the current device, or return an error speech."""
    device_id = (
        handler_input.request_envelope.context.system.device.device_id
    )
    household_id = get_household_id_for_device(device_id)
    return household_id


def get_slot_value(handler_input, slot_name):
    """Safely get a slot value from the intent."""
    slots = handler_input.request_envelope.request.intent.slots
    if slots and slot_name in slots and slots[slot_name].value:
        return slots[slot_name].value
    return None


def build_audio_response(handler_input, story):
    """Build an AudioPlayer.Play response for a story."""
    audio_url = get_audio_url(story["audioKey"])
    if not audio_url:
        return (
            handler_input.response_builder
            .speak("Sorry, I couldn't find the audio for that story.")
            .response
        )

    reader_name = get_reader_display_name(story["readerId"])
    title = story["title"]

    return (
        handler_input.response_builder
        .speak(f"Playing {title}, read by {reader_name}.")
        .add_directive(
            PlayDirective(
                play_behavior=PlayBehavior.REPLACE_ALL,
                audio_item=AudioItem(
                    stream=Stream(
                        token=story["storyId"],
                        url=audio_url,
                        offset_in_milliseconds=0,
                    ),
                ),
            )
        )
        .set_should_end_session(True)
        .response
    )


# --- Request Handlers ---


class LaunchRequestHandler(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return is_request_type("LaunchRequest")(handler_input)

    def handle(self, handler_input):
        household_id = get_household_or_fail(handler_input)
        if not household_id:
            return (
                handler_input.response_builder
                .speak(NO_DEVICE_LINKED)
                .response
            )

        speech = (
            "Welcome to Tuck Me In! "
            "You can say things like 'play Daddy reading Goodnight Moon', "
            "'what stories are available', or 'read me anything'. "
            "What would you like to hear?"
        )
        return (
            handler_input.response_builder
            .speak(speech)
            .ask("What story would you like to hear?")
            .response
        )


class PlayStoryIntentHandler(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return is_intent_name("PlayStoryIntent")(handler_input)

    def handle(self, handler_input):
        household_id = get_household_or_fail(handler_input)
        if not household_id:
            return (
                handler_input.response_builder
                .speak(NO_DEVICE_LINKED)
                .response
            )

        reader = get_slot_value(handler_input, "reader")
        title = get_slot_value(handler_input, "title")

        if not title:
            return (
                handler_input.response_builder
                .speak("Which story would you like to hear?")
                .ask("Tell me the name of the story you'd like to hear.")
                .response
            )

        story = get_story_by_title(household_id, title, reader)

        if not story:
            if reader:
                speech = f"I couldn't find a story called {title} from {reader}. "
            else:
                speech = f"I couldn't find a story called {title}. "
            speech += "You can say 'what stories are available' to see what's ready."
            return (
                handler_input.response_builder
                .speak(speech)
                .ask("Would you like to hear a different story?")
                .response
            )

        return build_audio_response(handler_input, story)


class ListStoriesIntentHandler(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return is_intent_name("ListStoriesIntent")(handler_input)

    def handle(self, handler_input):
        household_id = get_household_or_fail(handler_input)
        if not household_id:
            return (
                handler_input.response_builder
                .speak(NO_DEVICE_LINKED)
                .response
            )

        reader = get_slot_value(handler_input, "reader")
        stories = get_stories_for_household(household_id, reader)

        if not stories:
            if reader:
                speech = f"{reader} hasn't recorded any stories yet. "
            else:
                speech = "There aren't any stories available yet. "
            speech += "Ask a family member to record one in the Tuck Me In app."
            return (
                handler_input.response_builder
                .speak(speech)
                .response
            )

        if len(stories) == 1:
            s = stories[0]
            reader_name = get_reader_display_name(s["readerId"])
            speech = f"You have one story: {s['title']}, read by {reader_name}. Would you like to hear it?"
            return (
                handler_input.response_builder
                .speak(speech)
                .ask("Would you like me to play it?")
                .response
            )

        story_list = []
        for s in stories[:10]:  # Limit to 10 for voice readability
            reader_name = get_reader_display_name(s["readerId"])
            story_list.append(f"{s['title']} by {reader_name}")

        stories_text = ", ".join(story_list[:-1]) + f", and {story_list[-1]}"
        speech = f"You have {len(stories)} stories: {stories_text}. Which one would you like to hear?"

        return (
            handler_input.response_builder
            .speak(speech)
            .ask("Which story would you like to hear?")
            .response
        )


class RequestStoryIntentHandler(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return is_intent_name("RequestStoryIntent")(handler_input)

    def handle(self, handler_input):
        household_id = get_household_or_fail(handler_input)
        if not household_id:
            return (
                handler_input.response_builder
                .speak(NO_DEVICE_LINKED)
                .response
            )

        reader = get_slot_value(handler_input, "reader")
        title = get_slot_value(handler_input, "title")

        if not reader or not title:
            return (
                handler_input.response_builder
                .speak(
                    "I need to know who should read the story and what story you'd like. "
                    "Try saying something like 'ask Daddy to read Goodnight Moon'."
                )
                .ask("Who should read the story, and what's the title?")
                .response
            )

        result = create_story_request(household_id, reader, title)

        if not result:
            speech = (
                f"I couldn't find {reader} in your family. "
                "Make sure they've set up their profile in the Tuck Me In app."
            )
            return (
                handler_input.response_builder
                .speak(speech)
                .response
            )

        speech = (
            f"I've sent a request to {reader} to record {title}. "
            "They'll get a notification in the Tuck Me In app. "
            "I'll let you know when it's ready!"
        )
        return (
            handler_input.response_builder
            .speak(speech)
            .response
        )


class RandomStoryIntentHandler(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return is_intent_name("RandomStoryIntent")(handler_input)

    def handle(self, handler_input):
        household_id = get_household_or_fail(handler_input)
        if not household_id:
            return (
                handler_input.response_builder
                .speak(NO_DEVICE_LINKED)
                .response
            )

        reader = get_slot_value(handler_input, "reader")
        story = get_random_story(household_id, reader)

        if not story:
            speech = "There aren't any stories available yet. Ask a family member to record one in the Tuck Me In app."
            return (
                handler_input.response_builder
                .speak(speech)
                .response
            )

        return build_audio_response(handler_input, story)


# --- AudioPlayer Handlers ---


class PauseIntentHandler(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return (
            is_intent_name("AMAZON.PauseIntent")(handler_input)
            or is_intent_name("AMAZON.StopIntent")(handler_input)
            or is_intent_name("AMAZON.CancelIntent")(handler_input)
        )

    def handle(self, handler_input):
        return (
            handler_input.response_builder
            .add_directive(StopDirective())
            .set_should_end_session(True)
            .response
        )


class ResumeIntentHandler(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return is_intent_name("AMAZON.ResumeIntent")(handler_input)

    def handle(self, handler_input):
        # Retrieve playback state from AudioPlayer context
        playback_info = (
            handler_input.request_envelope.context.audio_player
        )

        if playback_info and playback_info.token and playback_info.offset_in_milliseconds is not None:
            # Look up story by token (storyId)
            import os
            import boto3
            dynamodb = boto3.resource("dynamodb")
            stories_table = dynamodb.Table(os.environ.get("STORIES_TABLE", "tuck-me-in-stories"))
            result = stories_table.get_item(Key={"storyId": playback_info.token})
            story = result.get("Item")

            if story:
                from utils import get_audio_url, get_reader_display_name
                audio_url = get_audio_url(story["audioKey"])
                reader_name = get_reader_display_name(story["readerId"])

                return (
                    handler_input.response_builder
                    .speak(f"Resuming {story['title']} by {reader_name}.")
                    .add_directive(
                        PlayDirective(
                            play_behavior=PlayBehavior.REPLACE_ALL,
                            audio_item=AudioItem(
                                stream=Stream(
                                    token=playback_info.token,
                                    url=audio_url,
                                    offset_in_milliseconds=playback_info.offset_in_milliseconds,
                                ),
                            ),
                        )
                    )
                    .set_should_end_session(True)
                    .response
                )

        return (
            handler_input.response_builder
            .speak("I don't have a story to resume. What would you like to hear?")
            .ask("What story would you like to hear?")
            .response
        )


class AudioPlayerEventHandler(AbstractRequestHandler):
    """Handle AudioPlayer events (PlaybackStarted, PlaybackFinished, etc.)."""

    def can_handle(self, handler_input):
        return handler_input.request_envelope.request.object_type.startswith(
            "AudioPlayer."
        )

    def handle(self, handler_input):
        return handler_input.response_builder.response


# --- Fallback & Error Handlers ---


class HelpIntentHandler(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return is_intent_name("AMAZON.HelpIntent")(handler_input)

    def handle(self, handler_input):
        speech = (
            "Tuck Me In plays bedtime stories recorded by your family. "
            "Here's what you can say: "
            "'Play Daddy reading Goodnight Moon' to hear a specific story. "
            "'What stories are available' to see your library. "
            "'Read me anything' for a surprise story. "
            "Or 'Ask Mommy to read The Cat in the Hat' to request a new recording. "
            "What would you like to do?"
        )
        return (
            handler_input.response_builder
            .speak(speech)
            .ask("What would you like to do?")
            .response
        )


class FallbackIntentHandler(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return is_intent_name("AMAZON.FallbackIntent")(handler_input)

    def handle(self, handler_input):
        speech = (
            "I didn't quite get that. "
            "You can say 'play' followed by a story name, "
            "'what stories are available', or 'read me anything'. "
            "What would you like to hear?"
        )
        return (
            handler_input.response_builder
            .speak(speech)
            .ask("What story would you like to hear?")
            .response
        )


class SessionEndedRequestHandler(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return is_request_type("SessionEndedRequest")(handler_input)

    def handle(self, handler_input):
        return handler_input.response_builder.response


class CatchAllExceptionHandler(AbstractExceptionHandler):
    def can_handle(self, handler_input, exception):
        return True

    def handle(self, handler_input, exception):
        logger.error(f"Error: {exception}", exc_info=True)
        speech = "Sorry, something went wrong. Please try again."
        return (
            handler_input.response_builder
            .speak(speech)
            .ask(speech)
            .response
        )


# --- Skill Builder ---

sb = SkillBuilder()

sb.add_request_handler(LaunchRequestHandler())
sb.add_request_handler(PlayStoryIntentHandler())
sb.add_request_handler(ListStoriesIntentHandler())
sb.add_request_handler(RequestStoryIntentHandler())
sb.add_request_handler(RandomStoryIntentHandler())
sb.add_request_handler(PauseIntentHandler())
sb.add_request_handler(ResumeIntentHandler())
sb.add_request_handler(AudioPlayerEventHandler())
sb.add_request_handler(HelpIntentHandler())
sb.add_request_handler(FallbackIntentHandler())
sb.add_request_handler(SessionEndedRequestHandler())

sb.add_exception_handler(CatchAllExceptionHandler())

lambda_handler = sb.lambda_handler()
