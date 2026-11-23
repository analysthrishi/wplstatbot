import logging
import os

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

from chain import UnsafeQueryError, build_chain, connect_readonly

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("wplstatbot")

MAX_QUESTIONS_PER_SESSION = 20
MAX_QUESTION_LENGTH = 300

# Load environment variables (.env locally; Streamlit Cloud exposes secrets as env vars)
load_dotenv()
api_key = os.getenv("GOOGLE_API_KEY")


@st.cache_resource
def get_chain(key):
    logger.info("Building SQL chain")
    return build_chain(key)[2]


@st.cache_data
def get_popular_players():
    """Get some popular players for examples"""
    try:
        conn = connect_readonly()
        try:
            df = pd.read_sql_query("""
                SELECT p.player_name, COUNT(DISTINCT b.match_id) as matches
                FROM balls b
                JOIN players p ON b.batter_id = p.player_id
                GROUP BY p.player_id, p.player_name
                ORDER BY matches DESC
                LIMIT 10
            """, conn)
        finally:
            conn.close()
        return df['player_name'].tolist()
    except Exception:
        logger.exception("Could not load popular players")
        return ["H Kaur", "NR Sciver-Brunt", "EA Perry", "S Mandhana", "A Sutherland"]


@st.cache_data(ttl=3600, show_spinner=False)
def get_answer_from_chain(question):
    """Answers are cached for an hour so repeated questions don't hit the Gemini API again."""
    return get_chain(api_key).invoke({"question": question})


# --- Streamlit UI ---
st.title("WPL Data Assistant 🏏")

if not api_key:
    st.error("API Key not found! Set GOOGLE_API_KEY in your .env file or Streamlit secrets.")
    st.stop()

# Player Naming Guide
with st.expander("📋 Player Naming Convention & Examples", expanded=False):
    st.markdown("""
    **How players are named in the database:**

    Players are typically referred to by **Initial(s) + Surname** format:

    | Full Name | Database Name | Example Query |
    |-----------|---------------|---------------|
    | Harmanpreet Kaur | H Kaur | "H Kaur batting stats" |
    | Natalie Ruth Sciver-Brunt | NR Sciver-Brunt | "NR Sciver-Brunt bowling stats" |
    | Ellyse Alexandra Perry | EA Perry | "EA Perry batting stats" |
    | Annabel Sutherland | A Sutherland | "A Sutherland bowling stats" |
    | Hayley Kristen Matthews | HK Matthews | "HK Matthews stats" |

    **Patterns:**
    - **Single Initial**: A Gardner (Ashleigh Gardner)
    - **Double Initials**: NR Sciver-Brunt (Natalie Ruth Sciver-Brunt)
    - **Triple Initials**: IECM Wong (Issy Wong)
    - **Full Names**: Some players use full names (e.g., AJ Healy)

    **Popular Players in WPL:**
    """)

    popular_players = get_popular_players()
    cols = st.columns(3)
    for i, player in enumerate(popular_players):
        cols[i % 3].write(f"• {player}")

    st.markdown("""
    **Tips:**
    - Full names work too: "Harmanpreet Kaur batting stats" is read as "H Kaur batting stats"
    - For batting stats: "Player Name batting stats"
    - For bowling stats: "Player Name bowling stats"
    - For team queries: Use full team names (e.g., "Delhi Capitals", "Mumbai Indians")
    """)


def clear_input():
    st.session_state.query = ""


st.session_state.setdefault("questions_asked", 0)

user_input = st.text_input(
    "Ask anything about WPL (e.g., 'H Kaur batting stats', 'Top 5 run getters against Delhi Capitals')",
    key="query",
    max_chars=MAX_QUESTION_LENGTH,
)

st.button("Clear Input", on_click=clear_input)

if user_input:
    question = user_input.strip()
    # Streamlit reruns the script on every interaction; only count a question once.
    is_new_question = question != st.session_state.get("last_question")
    if is_new_question and st.session_state.questions_asked >= MAX_QUESTIONS_PER_SESSION:
        st.warning(
            f"You've reached the limit of {MAX_QUESTIONS_PER_SESSION} questions for this session. "
            "Please come back later."
        )
    else:
        if is_new_question:
            st.session_state.questions_asked += 1
            st.session_state.last_question = question
        with st.spinner("Generating response..."):
            try:
                answer = get_answer_from_chain(question)
            except UnsafeQueryError:
                logger.warning("Rejected unsafe query for question: %r", question)
                answer = "Sorry, I can only answer questions that read WPL statistics."
            except Exception:
                logger.exception("Chain failed for question: %r", question)
                answer = "Sorry, something went wrong while answering that. Please try rephrasing your question."
        st.write(answer)
