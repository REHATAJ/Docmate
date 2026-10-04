import json
import time

import streamlit as st
from google import genai
from google.genai import types
from twilio.rest import Client as TwilioClient

from prompts import (
    SYSTEM_PROMPT,
    WELCOME_MESSAGE_TEMPLATE,
    REPORT_IMAGE_PROMPT,
    SUMMARY_REQUEST_PROMPT,
)


# ============================================================
# APP CONFIGURATION
# ============================================================

MODEL_NAME = "gemini-3.8-flash"
FALLBACK_MODEL = "gemini-3.7-flash"

st.set_page_config(
    page_title="DocMate",
    page_icon="🩺",
    layout="centered",
)


# ============================================================
# API CONFIGURATION
# ============================================================

GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]

TWILIO_ACCOUNT_SID = st.secrets["TWILIO_ACCOUNT_SID"]
TWILIO_AUTH_TOKEN = st.secrets["TWILIO_AUTH_TOKEN"]
TWILIO_WHATSAPP_FROM = st.secrets["TWILIO_WHATSAPP_FROM"]
TWILIO_CONTENT_SID = st.secrets["TWILIO_CONTENT_SID"]


# ============================================================
# CLIENTS
# ============================================================

@st.cache_resource
def get_gemini_client():

    return genai.Client(
        api_key=GEMINI_API_KEY
    )


@st.cache_resource
def get_twilio_client():

    return TwilioClient(
        TWILIO_ACCOUNT_SID,
        TWILIO_AUTH_TOKEN,
    )


gemini_client = get_gemini_client()
twilio_client = get_twilio_client()


# ============================================================
# CREATE GEMINI CHAT
# ============================================================

def create_gemini_chat(model_name):

    return gemini_client.chats.create(
        model=model_name,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT
        ),
    )


# ============================================================
# MESSAGE FUNCTIONS
# ============================================================

def render_message(message):

    with st.chat_message(message["role"]):

        if message["kind"] == "text":

            st.markdown(
                message["content"]
            )

        elif message["kind"] == "image":

            st.image(
                message["content"],
                use_container_width=True,
            )


def add_message(role, kind, content):

    message = {
        "role": role,
        "kind": kind,
        "content": content,
    }

    st.session_state.messages.append(
        message
    )

    render_message(message)


# ============================================================
# GEMINI
# ============================================================

def ask_gemini(parts):

    # --------------------------------------------------------
    # FIRST MODEL
    # --------------------------------------------------------

    for attempt in range(3):

        try:

            response = st.session_state.chat.send_message(
                parts
            )

            return response.text

        except Exception as error:

            error_text = str(error)

            temporary_error = (
                "503" in error_text
                or "UNAVAILABLE" in error_text
                or "429" in error_text
                or "RESOURCE_EXHAUSTED" in error_text
            )

            if temporary_error and attempt < 2:

                wait_time = 2 ** attempt

                time.sleep(wait_time)

                continue

            break


    # --------------------------------------------------------
    # FALLBACK MODEL
    # --------------------------------------------------------

    try:

        st.session_state.chat = create_gemini_chat(
            FALLBACK_MODEL
        )

        st.session_state.current_model = FALLBACK_MODEL

        response = st.session_state.chat.send_message(
            parts
        )

        return response.text

    except Exception as fallback_error:

        return (
            "Sorry, I couldn't analyze the report right now.\n\n"
            "Gemini is temporarily unavailable. "
            "Please try again in a moment.\n\n"
            f"Error: {fallback_error}"
        )


# ============================================================
# WHATSAPP
# ============================================================

def clean_whatsapp_text(text):

    if not text:

        return "No report summary is available."

    text = " ".join(
        text.split()
    )

    if len(text) > 1500:

        text = text[:1500] + "..."

    return text


def send_whatsapp(
    to_number,
    user_name,
    summary,
):

    try:

        content_variables = json.dumps(
            {
                "1": user_name,
                "2": clean_whatsapp_text(summary),
            },
            ensure_ascii=False,
        )

        message = twilio_client.messages.create(
            from_=TWILIO_WHATSAPP_FROM,
            to=f"whatsapp:{to_number}",
            content_sid=TWILIO_CONTENT_SID,
            content_variables=content_variables,
        )

        return True, message.sid

    except Exception as error:

        return False, str(error)


# ============================================================
# ONBOARDING
# ============================================================

if "onboarded" not in st.session_state:

    st.title("DocMate 🩺")

    st.caption(
        "Understand your medical reports in simple language."
    )

    with st.form("onboarding_form"):

        name = st.text_input(
            "Your name",
            placeholder="Enter your name",
        )

        whatsapp_number = st.text_input(
            "WhatsApp number",
            placeholder="+91XXXXXXXXXX",
            help=(
                "Include your country code. "
                "We'll use this to send your report summary."
            ),
        )

        submitted = st.form_submit_button(
            "Continue 🚀"
        )

    if submitted:

        if (
            not name.strip()
            or not whatsapp_number.strip()
        ):

            st.warning(
                "Please enter both your name and WhatsApp number."
            )

        else:

            st.session_state.name = (
                name.strip()
            )

            st.session_state.whatsapp_number = (
                whatsapp_number.strip()
            )

            # Create primary Gemini chat
            st.session_state.chat = create_gemini_chat(
                MODEL_NAME
            )

            st.session_state.current_model = MODEL_NAME

            st.session_state.messages = []

            st.session_state.report_uploaded = False

            st.session_state.onboarded = True

            st.rerun()

    st.stop()


# ============================================================
# HEADER
# ============================================================

header_col, button_col = st.columns(
    [5, 2],
    vertical_alignment="center",
)


with header_col:

    st.title("DocMate 🩺")


with button_col:

    send_disabled = not st.session_state.get(
        "report_uploaded",
        False,
    )

    if st.button(
        "📤 WhatsApp",
        disabled=send_disabled,
        use_container_width=True,
    ):

        with st.spinner(
            "Preparing your report summary..."
        ):

            summary = ask_gemini(
                [SUMMARY_REQUEST_PROMPT]
            )

        success, info = send_whatsapp(
            st.session_state.whatsapp_number,
            st.session_state.name,
            summary,
        )

        if success:

            st.success(
                "Report summary sent to WhatsApp 📲"
            )

        else:

            st.error(
                f"Couldn't send the summary: {info}"
            )


st.caption(
    f"Logged in as {st.session_state.name}"
)


# ============================================================
# CHAT HISTORY
# ============================================================

if not st.session_state.messages:

    add_message(
        "assistant",
        "text",
        WELCOME_MESSAGE_TEMPLATE.format(
            name=st.session_state.name
        ),
    )

else:

    for message in st.session_state.messages:

        render_message(message)


# ============================================================
# REPORT UPLOAD
# ============================================================

user_input = st.chat_input(
    "Ask about your report or upload an image 📄",
    accept_file=True,
    file_type=[
        "jpg",
        "jpeg",
        "png",
        "webp",
    ],
)


# ============================================================
# PROCESS USER INPUT
# ============================================================

if user_input:

    photo = (
        user_input.files[0]
        if user_input.files
        else None
    )

    text = user_input.text

    parts = []


    # ========================================================
    # IMAGE
    # ========================================================

    if photo is not None:

        photo_bytes = photo.getvalue()

        # Show uploaded report
        add_message(
            "user",
            "image",
            photo_bytes,
        )

        # Tell Gemini to analyze report
        parts.append(
            REPORT_IMAGE_PROMPT
        )

        # Send image to Gemini
        parts.append(
            types.Part.from_bytes(
                data=photo_bytes,
                mime_type=photo.type,
            )
        )

        st.session_state.report_uploaded = True


    # ========================================================
    # TEXT
    # ========================================================

    if text:

        add_message(
            "user",
            "text",
            text,
        )

        parts.append(
            text
        )


    # ========================================================
    # IMAGE ONLY
    # ========================================================

    elif photo is not None:

        pass


    # ========================================================
    # ASK GEMINI
    # ========================================================

    if parts:

        with st.spinner(
            "Reading and analyzing your report..."
        ):

            answer = ask_gemini(
                parts
            )

        add_message(
            "assistant",
            "text",
            answer,
        )