import streamlit as st
from io import BytesIO
from PyPDF2 import PdfReader
from google import genai
import json
import os
from dotenv import load_dotenv
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
from streamlit_oauth import OAuth2Component

load_dotenv()

api_key = st.secrets["API_KEY"]
if not api_key:
    st.error("API Key not found!")
    st.stop()
else:
    client = genai.Client(api_key=api_key)

CLIENT_ID = st.secrets["auth"]["client_id"]
CLIENT_SECRET = st.secrets["auth"]["client_secret"]
AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
REDIRECT_URI = st.secrets["auth"]["redirect_uri"]
SCOPE = "openid email profile https://www.googleapis.com/auth/calendar.events"

oauth2 = OAuth2Component(CLIENT_ID, CLIENT_SECRET, AUTHORIZE_URL, TOKEN_URL, TOKEN_URL, REVOKE_URL)

# --- Auth Gate ---
if 'token' not in st.session_state:
    st.title("Syllabus Parser")
    result = oauth2.authorize_button(
        name="Log in with Google",
        icon="https://www.google.com.hk/favicon.ico",
        redirect_uri=REDIRECT_URI,
        scope=SCOPE,
        key="google_auth",
    )
    if result and 'token' in result:
        st.session_state['token'] = result['token']
        st.rerun()
    st.stop()

# --- App (only reaches here if logged in) ---
access_token = st.session_state['token']['access_token']
st.success("Logged in! Ready to parse your syllabus.")

def syncToCalendar(dates, token):
    creds = Credentials(token)
    service = build('calendar', 'v3', credentials=creds)
    for date in dates:
        if date['date'] == "TBD":
            continue
        event = {
            'summary': date['name'],
            'description': 'Added via Syllabus Parser',
            'start': {'date': date['date']},
            'end': {'date': date['date']},
        }
        service.events().insert(calendarId='primary', body=event).execute()
    st.success("Synced to Google Calendar!")

@st.cache_data
def extract_dates(syllabus):
    # Use GenAI to extract dates from the syllabus text
    prompt = (
    "Role: You are an expert Academic Data Extractor. "
    "Task: Extract only gradeable assignments, exams, quizzes, and project deadlines from the provided syllabus text. "

    "Exclusion Rules - DO NOT extract any of the following: "
    "office hours, discussion sections, seminars, lectures, lab sections, review sessions, "
    "class meetings, recitations, or any other non-graded recurring schedule items. "
    "Only include items that a student would receive a grade for. "

    "Naming Rules: "
    "1. If multiple events share the same type (e.g. Quiz, Homework, Lab), number them sequentially: 'Quiz 1', 'Quiz 2', etc. "
    "2. If an event has a specific topic or title mentioned, append it: 'Quiz 3 - Linked Lists'. "

    "Date Rules: "
    "1. The 'date' must be in YYYY-MM-DD format. Assume the year is 2026 unless stated otherwise. "
    "2. If a syllabus says something recurs on a specific weekday (e.g. 'every Friday'), "
    "calculate the actual calendar dates those Fridays fall on for the semester and generate one event per occurrence. "
    "3. If a date range is given (e.g. 'Week 3'), estimate the start date of that week. "
    "4. Only use 'TBD' as a last resort when absolutely no date information can be inferred. "

    "Output Format: Return ONLY a valid JSON object with a single key 'events' containing a flat list. "
    "Every object must have exactly two keys: 'name' (string) and 'date' (YYYY-MM-DD or 'TBD'). "
    "No markdown, no backticks, no explanation. "

    "Syllabus text:\n\n" + syllabus
    )
    response = client.models.generate_content(model='gemini-2.5-flash', contents=prompt)
    return response.text

syllabus = st.file_uploader("Upload Syllabus (PDF)", type="pdf")

if syllabus is not None:
    pdf_reader = PdfReader(BytesIO(syllabus.getvalue()))
    string_data = "".join(page.extract_text() for page in pdf_reader.pages)

    raw = extract_dates(string_data)
    try:
        raw = raw[raw.find("{"):raw.rfind("}") + 1]
        data = json.loads(raw)
    except json.JSONDecodeError:
        st.error("Failed to parse dates from syllabus. Try re-uploading.")
        st.stop()

    st.write("Select the dates you want to add to Google Calendar:")
    important_dates = data["events"]
    marked_dates = []
    for date in important_dates:
        if st.checkbox(f"{date['name']} — {date['date']}"):
            marked_dates.append(date)

    if marked_dates:
        st.write("Selected dates:")
        for d in marked_dates:
            st.write(f"- {d['name']} — {d['date']}")

    if st.button("Add to Google Calendar"):
        if not marked_dates:
            st.warning("No dates selected.")
        else:
            syncToCalendar(marked_dates, access_token)