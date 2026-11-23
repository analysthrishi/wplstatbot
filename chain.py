"""Shared text-to-SQL chain for WPL StatsBot (used by app.py and test.py)."""
import csv
import re
import sqlite3
from collections import defaultdict
from functools import lru_cache
from pathlib import Path

from langchain_community.utilities import SQLDatabase
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_classic.chains import create_sql_query_chain
from langchain_community.tools.sql_database.tool import QuerySQLDatabaseTool
from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import RunnablePassthrough

DB_PATH = Path(__file__).resolve().parent / "wpl.db"
# Read-only URI: any write (DROP/DELETE/UPDATE...) the LLM might generate fails at the SQLite level.
DB_URI = f"file:{DB_PATH.as_posix()}?mode=ro"
ALIASES_PATH = Path(__file__).resolve().parent / "player_aliases.csv"
MODEL = "gemini-2.5-flash-lite"


def connect_readonly():
    return sqlite3.connect(DB_URI, uri=True)


# Words that commonly sit right before a surname in a question ("who dismissed Dottin").
# The surname fallback never treats these as a first name.
_NOT_FIRST_NAMES = {
    "a", "an", "the", "by", "of", "for", "vs", "versus", "against", "and", "or", "to", "in", "on",
    "at", "with", "who", "whom", "whose", "did", "does", "do", "has", "have", "had", "is", "was",
    "are", "were", "dismissed", "dismiss", "dismisses", "dismissing", "out", "got", "get", "gets",
    "bowled", "bowl", "bowls", "bowling", "bat", "bats", "batting", "batted", "stats",
    "statistics", "runs", "wickets", "top", "most", "best", "how", "many", "much", "what",
    "which", "scored", "score", "scores", "take", "taken", "took", "faced", "face", "between",
    "player", "players", "team", "compare", "record", "records", "career", "economy", "average",
    "strike", "rate", "innings", "matches", "season", "show", "give", "list", "me", "from",
    "her", "she", "all", "total", "about", "tell", "than", "more", "less", "dismissals",
}
_WORD = re.compile(r"[A-Za-z][A-Za-z'-]*")


@lru_cache(maxsize=1)
def _name_index():
    """Build (alias pattern, alias -> db name, surname -> [db names of players who played])."""
    conn = connect_readonly()
    try:
        all_names = [r[0] for r in conn.execute("SELECT player_name FROM players")]
        playing = [r[0] for r in conn.execute(
            "SELECT DISTINCT p.player_name FROM players p "
            "JOIN match_players mp ON mp.player_id = p.player_id"
        )]
    finally:
        conn.close()

    lookup = {name.lower(): name for name in all_names}
    with open(ALIASES_PATH, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            lookup[row["alias"].strip().lower()] = row["player_name"].strip()

    # Longest first so "Shafali Verma" wins over "S Verma", "Ellyse Perry" over "Perry".
    alternatives = "|".join(re.escape(k) for k in sorted(lookup, key=len, reverse=True))
    pattern = re.compile(rf"(?<![\w'-])(?:{alternatives})(?![\w'-])", re.I)

    by_surname = defaultdict(list)
    for name in playing:
        parts = name.split()
        if len(parts) >= 2:
            by_surname[parts[-1].lower()].append(name)
    return pattern, lookup, by_surname


def resolve_player_names(question):
    """Rewrite player names in a question to their exact database names.

    "harmanpreet kaur batting stats" -> "H Kaur batting stats". Names are matched against
    player_aliases.csv and the database names; anything else falls back to a surname match,
    using the preceding word's initial to pick between players sharing a surname.
    Ambiguous names are left unchanged.
    """
    pattern, lookup, by_surname = _name_index()

    # Pass 1: known names/aliases -> placeholders, so pass 2 can't touch them.
    resolved = []

    def to_placeholder(match):
        resolved.append(lookup[match.group(0).lower()])
        return f"\x00{len(resolved) - 1}\x00"

    text = pattern.sub(to_placeholder, question)

    # Pass 2: surname fallback for names not in the alias file.
    words = list(_WORD.finditer(text))
    replacements = []  # (start, end, db_name)
    consumed = set()
    for i, word in enumerate(words):
        candidates = by_surname.get(word.group(0).lower())
        if not candidates or i in consumed:
            continue
        prev = words[i - 1] if i > 0 and (i - 1) not in consumed else None
        if prev is not None and (
            text[prev.end():word.start()].strip()  # not directly adjacent
            or prev.group(0).lower() in _NOT_FIRST_NAMES
        ):
            prev = None
        if prev is not None:
            initial = prev.group(0)[0].lower()
            matches = [c for c in candidates if c[0].lower() == initial]
            if len(matches) == 1:
                replacements.append((prev.start(), word.end(), matches[0]))
                consumed.update({i - 1, i})
                continue
        if len(candidates) == 1:
            replacements.append((word.start(), word.end(), candidates[0]))
            consumed.add(i)

    for start, end, name in reversed(replacements):
        text = text[:start] + name + text[end:]

    return re.sub(r"\x00(\d+)\x00", lambda m: resolved[int(m.group(1))], text)


# Custom prompt for SQL generation with cricket-specific rules
sql_generation_prompt = PromptTemplate(
    input_variables=["input", "table_info", "top_k"],
    template="""You are a SQLite expert for Women's Premier League (WPL) cricket data.
Given an input question, create a syntactically correct SQLite query.

ONLY use the following tables and schema:
{table_info}

CRITICAL CRICKET RULES:
- Player names in the question are already exact database names (e.g. 'H Kaur', 'NR Sciver-Brunt'). Match them with p.player_name = '<name>' exactly as written; do not expand or change them.
- "Against" a team means runs/wickets scored TAKEN by players FROM OTHER TEAMS in matches involving that team.
  For example, "runs against Delhi Capitals" means runs scored by non-DC players in matches where DC played.
  Filter: JOIN balls b ON matches m ON b.match_id = m.match_id WHERE (m.team1 = 'Delhi Capitals' OR m.team2 = 'Delhi Capitals') AND b.batting_team != 'Delhi Capitals'
- "For" a team means runs scored by players FROM that team.
- Always JOIN 'players' p ON p.player_id = b.batter_id (or bowler_id) to get player names.
- Balls faced (batting) = legal deliveries only, EXCLUDING wides: SUM(CASE WHEN b.extras_wides IS NULL THEN 1 ELSE 0 END). No-balls DO count as balls faced. Never use COUNT(*) or COUNT(b.ball_id) for balls faced.
- Balls bowled (bowling) = legal deliveries only, EXCLUDING wides and no-balls: SUM(CASE WHEN b.extras_wides IS NULL AND b.extras_noballs IS NULL THEN 1 ELSE 0 END). Never use COUNT(*) or COUNT(b.ball_id) for balls bowled.
- Batting innings = matches where the player was at the crease (as striker OR non-striker), so a player run out without facing still counts: (SELECT COUNT(*) FROM (SELECT match_id FROM balls WHERE batter_id = p.player_id UNION SELECT match_id FROM balls WHERE non_striker_id = p.player_id))
- Bowling innings = COUNT(DISTINCT b.match_id) over rows joined on b.bowler_id (matches in which the player bowled).
- For strike rate: SUM(b.runs_batter) * 100.0 / balls faced (as defined above)
- Bowler wickets: Only count where wickets.kind NOT IN ('run out', 'retired hurt', 'obstructing the field')
- For batting stats of a player, SELECT: p.player_name, (SELECT COUNT(*) FROM (SELECT match_id FROM balls WHERE batter_id = p.player_id UNION SELECT match_id FROM balls WHERE non_striker_id = p.player_id)) AS innings, SUM(b.runs_batter) AS runs, SUM(CASE WHEN b.extras_wides IS NULL THEN 1 ELSE 0 END) AS balls, ROUND(SUM(b.runs_batter) * 100.0 / NULLIF(SUM(CASE WHEN b.extras_wides IS NULL THEN 1 ELSE 0 END), 0), 2) AS strike_rate FROM balls b JOIN players p ON b.batter_id = p.player_id WHERE p.player_name = 'Player Name' GROUP BY p.player_id, p.player_name
- For bowling stats of a player, SELECT: p.player_name, COUNT(DISTINCT b.match_id) AS innings, SUM(CASE WHEN b.extras_wides IS NULL AND b.extras_noballs IS NULL THEN 1 ELSE 0 END) AS balls, SUM(b.runs_total) AS runs_conceded, COUNT(w.ball_id) AS wickets, ROUND(SUM(b.runs_total) * 6.0 / NULLIF(SUM(CASE WHEN b.extras_wides IS NULL AND b.extras_noballs IS NULL THEN 1 ELSE 0 END), 0), 2) AS economy, ROUND((SUM(b.runs_total) * 1.0 / NULLIF(COUNT(w.ball_id), 0)), 2) AS average FROM balls b JOIN players p ON b.bowler_id = p.player_id LEFT JOIN wickets w ON b.ball_id = w.ball_id AND w.kind NOT IN ('run out', 'retired hurt', 'obstructing the field') WHERE p.player_name = 'Player Name' GROUP BY p.player_id, p.player_name
- For team performance/wins/standings, SELECT: team_name, COUNT(*) AS matches_played, SUM(CASE WHEN winner = team_name THEN 1 ELSE 0 END) AS wins, SUM(CASE WHEN winner != team_name AND winner IS NOT NULL THEN 1 ELSE 0 END) AS losses, ROUND((SUM(CASE WHEN winner = team_name THEN 1 ELSE 0 END) * 100.0 / COUNT(*)), 2) AS win_percentage FROM (SELECT team1 AS team_name, winner FROM matches UNION ALL SELECT team2 AS team_name, winner FROM matches) GROUP BY team_name ORDER BY wins DESC
- For top run scorers, SELECT p.player_name as player, SUM(b.runs_batter) as runs, (SELECT COUNT(*) FROM (SELECT match_id FROM balls WHERE batter_id = p.player_id UNION SELECT match_id FROM balls WHERE non_striker_id = p.player_id)) as innings, SUM(CASE WHEN b.extras_wides IS NULL THEN 1 ELSE 0 END) as balls, ROUND(SUM(b.runs_batter) * 100.0 / NULLIF(SUM(CASE WHEN b.extras_wides IS NULL THEN 1 ELSE 0 END), 0), 2) as strike_rate FROM balls b JOIN players p ON b.batter_id = p.player_id GROUP BY p.player_id, p.player_name ORDER BY runs DESC LIMIT {top_k}
- For top wicket takers, SELECT p.player_name as player, COUNT(w.ball_id) as wickets, COUNT(DISTINCT b.match_id) as innings, SUM(CASE WHEN b.extras_wides IS NULL AND b.extras_noballs IS NULL THEN 1 ELSE 0 END) as balls, SUM(b.runs_total) as runs_conceded, ROUND(SUM(b.runs_total) * 6.0 / NULLIF(SUM(CASE WHEN b.extras_wides IS NULL AND b.extras_noballs IS NULL THEN 1 ELSE 0 END), 0), 2) as economy, ROUND((SUM(b.runs_total) * 1.0 / NULLIF(COUNT(w.ball_id), 0)), 2) as average FROM balls b JOIN players p ON b.bowler_id = p.player_id LEFT JOIN wickets w ON b.ball_id = w.ball_id AND w.kind NOT IN ('run out', 'retired hurt', 'obstructing the field') GROUP BY p.player_id, p.player_name ORDER BY wickets DESC LIMIT {top_k}
- Limit to {top_k} unless specified otherwise.

Question: {input}
Return only the SQL query without any markdown formatting or code blocks: """
)

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


class UnsafeQueryError(ValueError):
    """Raised when the generated SQL is not a single read-only SELECT/WITH statement."""


def clean_sql(query):
    """Strip markdown fences from LLM output and allow only a single SELECT/WITH statement."""
    if "```" in query:
        for part in query.split("```"):
            part = part.strip()
            if part.lower().startswith(("sqlite", "sql")):
                part = re.sub(r"^(sqlite|sql)\b", "", part, flags=re.I).strip()
            if part and "SELECT" in part.upper():
                query = part
                break
    query = query.replace("```", "").strip().rstrip(";").strip()

    if not re.match(r"^(SELECT|WITH)\b", query, re.I):
        raise UnsafeQueryError("Only SELECT queries are allowed.")
    if ";" in query:
        raise UnsafeQueryError("Only a single SQL statement is allowed.")
    return query


def build_chain(api_key):
    """Build the question -> SQL -> answer chain. Returns (write_query, execute_query, chain)."""
    db = SQLDatabase.from_uri(f"sqlite:///{DB_URI}&uri=true")
    llm = ChatGoogleGenerativeAI(model=MODEL, google_api_key=api_key, temperature=0)

    execute_query = QuerySQLDatabaseTool(db=db)
    write_query = create_sql_query_chain(llm, db, prompt=sql_generation_prompt)

    chain = (
        RunnablePassthrough.assign(question=lambda x: resolve_player_names(x["question"]))
        .assign(query=lambda x: clean_sql(write_query.invoke({"question": x["question"]})))
        .assign(result=lambda x: execute_query.invoke(x["query"]))
        | answer_prompt
        | llm
        | StrOutputParser()
    )
    return write_query, execute_query, chain
