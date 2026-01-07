import streamlit as st
import sqlite3
import pandas as pd
import os
from dotenv import load_dotenv
from langchain_community.utilities import SQLDatabase
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_classic.chains import create_sql_query_chain
from langchain_community.tools.sql_database.tool import QuerySQLDatabaseTool
from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import RunnablePassthrough

# Load environment variables
load_dotenv()

# Fetch the key using os.getenv
api_key = os.getenv("GOOGLE_API_KEY")

# Configure Gemini
if not api_key:
    st.error("API Key not found! Please check your .env file.")

# 1. Setup Database Connection
db = SQLDatabase.from_uri("sqlite:///wpl.db")

# 2. Initialize Gemini
llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash-lite", google_api_key=api_key, temperature=0)

# 3. Create the SQL Generation Chain
execute_query = QuerySQLDatabaseTool(db=db)

# Custom prompt for SQL generation with cricket-specific rules
sql_generation_prompt = PromptTemplate(
    input_variables=["input", "table_info", "top_k"],
    template="""You are a SQLite expert for Women's Premier League (WPL) cricket data.
Given an input question, create a syntactically correct SQLite query.

ONLY use the following tables and schema:
{table_info}

CRITICAL CRICKET RULES:
- "Against" a team means runs/wickets scored TAKEN by players FROM OTHER TEAMS in matches involving that team.
  For example, "runs against Delhi Capitals" means runs scored by non-DC players in matches where DC played.
  Filter: JOIN balls b ON matches m ON b.match_id = m.match_id WHERE (m.team1 = 'Delhi Capitals' OR m.team2 = 'Delhi Capitals') AND b.batting_team != 'Delhi Capitals'
- "For" a team means runs scored by players FROM that team.
- Always JOIN 'players' p ON p.player_id = b.batter_id (or bowler_id) to get player names.
- For strike rate: (SUM(runs_batter) * 100.0 / COUNT(*))
- Bowler wickets: Only count where wickets.kind NOT IN ('run out', 'retired hurt', 'obstructing the field')
- For batting stats of a player, SELECT: p.player_name, COUNT(DISTINCT b.match_id) AS innings, SUM(b.runs_batter) AS runs, COUNT(b.ball_id) AS balls, ROUND((SUM(b.runs_batter) * 100.0 / COUNT(b.ball_id)), 2) AS strike_rate FROM balls b JOIN players p ON b.batter_id = p.player_id WHERE p.player_name = 'Player Name' GROUP BY p.player_name
- For bowling stats of a player, SELECT: p.player_name, COUNT(DISTINCT b.match_id) AS innings, COUNT(b.ball_id) AS balls, SUM(b.runs_total) AS runs_conceded, COUNT(w.ball_id) AS wickets, ROUND((SUM(b.runs_total) * 6.0 / COUNT(b.ball_id)), 2) AS economy, ROUND((SUM(b.runs_total) * 1.0 / NULLIF(COUNT(w.ball_id), 0)), 2) AS average FROM balls b JOIN players p ON b.bowler_id = p.player_id LEFT JOIN wickets w ON b.ball_id = w.ball_id AND w.kind NOT IN ('run out', 'retired hurt', 'obstructing the field') WHERE p.player_name = 'Player Name' GROUP BY p.player_name- For team performance/wins/standings, SELECT: team_name, COUNT(*) AS matches_played, SUM(CASE WHEN winner = team_name THEN 1 ELSE 0 END) AS wins, SUM(CASE WHEN winner != team_name AND winner IS NOT NULL THEN 1 ELSE 0 END) AS losses, ROUND((SUM(CASE WHEN winner = team_name THEN 1 ELSE 0 END) * 100.0 / COUNT(*)), 2) AS win_percentage FROM (SELECT team1 AS team_name, winner FROM matches UNION ALL SELECT team2 AS team_name, winner FROM matches) GROUP BY team_name ORDER BY wins DESC- For top run scorers, SELECT p.player_name as player, SUM(b.runs_batter) as runs, COUNT(DISTINCT b.match_id) as innings, COUNT(b.ball_id) as balls, ROUND((SUM(b.runs_batter) * 100.0 / COUNT(b.ball_id)), 2) as strike_rate FROM balls b JOIN players p ON b.batter_id = p.player_id GROUP BY p.player_id, p.player_name ORDER BY runs DESC LIMIT {top_k}- For top wicket takers, SELECT p.player_name as player, COUNT(w.ball_id) as wickets, COUNT(DISTINCT b.match_id) as innings, COUNT(b.ball_id) as balls, SUM(b.runs_total) as runs_conceded, ROUND((SUM(b.runs_total) * 6.0 / COUNT(b.ball_id)), 2) as economy, ROUND((SUM(b.runs_total) * 1.0 / NULLIF(COUNT(w.ball_id), 0)), 2) as average FROM balls b JOIN players p ON b.bowler_id = p.player_id LEFT JOIN wickets w ON b.ball_id = w.ball_id AND w.kind NOT IN ('run out', 'retired hurt', 'obstructing the field') GROUP BY p.player_id, p.player_name ORDER BY wickets DESC LIMIT {top_k}- Limit to {top_k} unless specified otherwise.

Question: {input}
Return only the SQL query without any markdown formatting or code blocks: """
)

write_query = create_sql_query_chain(llm, db, prompt=sql_generation_prompt)

# 4. Define the Custom Answer Prompt
answer_prompt = PromptTemplate.from_template(
    """You are a WPL data expert. Given the user question, the SQL query, and the SQL result, provide a natural response.

    IMPORTANT: Use ONLY the exact numbers and data from the SQL Result. Do not make up or modify any statistics.

    FORMATTING RULES - ALWAYS FOLLOW THESE:
    1. Extract the values directly from the SQL Result tuple/list.
    2. For team standings/performance with multiple teams, format as a markdown table with columns: Team, Matches, Wins, Losses, Win %
    3. For player vs player dismissal stats, format as a markdown table with columns: Bowler, Innings, Runs, Dismissals
    4. For individual player batting stats, provide a one-line summary followed by a markdown table with columns: Player, Innings, Runs, Balls, Strike Rate
    5. For individual player bowling stats, provide a one-line summary followed by a markdown table with columns: Player, Innings, Balls, Runs Conceded, Wickets, Economy, Average
    6. For top run scorers, format as a markdown table with columns: Player, Runs, Innings, Balls, Strike Rate
    7. For top wicket takers, format as a markdown table with columns: Player, Wickets, Innings, Balls, Economy, Average
    8. For single team queries, provide a summary paragraph.
    9. Round decimal values to 2 places as shown in the result.
    10. If the result is empty, say "No data found."
    11. NEVER provide plain text summaries for stats that should be in tables. ALWAYS use the specified table format.

    Question: {question}
    SQL Query: {query}
    SQL Result: {result}
    Answer: """
)

# 5. Build the Final Chain
def clean_sql(query):
    # Remove markdown code blocks
    if '```' in query:
        parts = query.split('```')
        for part in parts:
            part = part.strip()
            if part and not part.startswith('sql') and 'SELECT' in part.upper():
                return part
    # Fallback: remove common prefixes
    query = query.replace('```sql', '').replace('```sqlite', '').replace('```', '').strip()
    return query

chain = (
    RunnablePassthrough.assign(query=lambda x: clean_sql(write_query.invoke({"question": x["question"]}))).assign(
        result=lambda x: execute_query.invoke(x["query"])
    )
    | answer_prompt
    | llm
    | StrOutputParser()
)

# --- Functions ---

def get_popular_players():
    """Get some popular players for examples"""
    conn = sqlite3.connect("wpl.db")
    try:
        # Get players who have played most matches
        df = pd.read_sql_query("""
            SELECT p.player_name, COUNT(DISTINCT b.match_id) as matches
            FROM balls b 
            JOIN players p ON b.batter_id = p.player_id 
            GROUP BY p.player_id, p.player_name 
            ORDER BY matches DESC 
            LIMIT 10
        """, conn)
        return df['player_name'].tolist()
    except Exception as e:
        return ["H Kaur", "NR Sciver-Brunt", "EA Perry", "S Mandhana", "A Sutherland"]
    finally:
        conn.close()

def get_answer_from_chain(question):
    try:
        response = chain.invoke({"question": question})
        return response
    except Exception as e:
        return f"Error: {str(e)}"

# --- Streamlit UI ---
st.title("WPL Data Assistant 🏏")

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
    - Use exact database names for best results
    - For batting stats: "Player Name batting stats"  
    - For bowling stats: "Player Name bowling stats"
    - For team queries: Use full team names (e.g., "Delhi Capitals", "Mumbai Indians")
    """)

def clear_input():
    st.session_state.query = ""

user_input = st.text_input("Ask anything about WPL (e.g., 'H Kaur batting stats', 'Top 5 run getters against Delhi Capitals')", key="query")

col1, col2 = st.columns([4, 1])
with col1:
    st.button("Clear Input", on_click=clear_input)
with col2:
    pass  # Placeholder for future buttons if needed

if user_input:
    with st.spinner("Generating response..."):
        answer = get_answer_from_chain(user_input)
    st.write(answer)