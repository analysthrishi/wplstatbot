"""Offline checks for player-name resolution (no Gemini API calls). Run: uv run python test_names.py"""
import csv

from chain import ALIASES_PATH, connect_readonly, resolve_player_names


def test_alias_targets_exist():
    conn = connect_readonly()
    try:
        db_names = {r[0] for r in conn.execute("SELECT player_name FROM players")}
    finally:
        conn.close()
    with open(ALIASES_PATH, newline="", encoding="utf-8") as f:
        missing = [row for row in csv.DictReader(f) if row["player_name"] not in db_names]
    assert not missing, f"Aliases point to unknown players: {missing}"


CASES = [
    # (question, expected)
    ("harmanpreet kaur batting stats", "H Kaur batting stats"),
    ("Harmanpreet Kaur batting stats", "H Kaur batting stats"),
    ("H Kaur batting stats", "H Kaur batting stats"),
    ("h kaur batting stats", "H Kaur batting stats"),
    ("Amanjot Kaur bowling stats", "AB Kaur bowling stats"),
    ("Kaur stats", "Kaur stats"),  # ambiguous: H Kaur / AB Kaur
    ("Shafali Verma batting stats", "Shafali Verma batting stats"),
    ("S Verma batting stats", "S Verma batting stats"),
    ("Smriti Mandhana vs Ellyse Perry", "S Mandhana vs EA Perry"),
    ("top 5 bowlers who dismissed Smriti Mandhana most", "top 5 bowlers who dismissed S Mandhana most"),
    ("Nat Sciver-Brunt bowling stats", "NR Sciver-Brunt bowling stats"),
    ("NR Sciver-Brunt bowling stats", "NR Sciver-Brunt bowling stats"),
    # Surname fallback (not via the alias file)
    ("Mandhana batting stats", "S Mandhana batting stats"),
    ("who dismissed Dottin most", "who dismissed DJS Dottin most"),
    ("Sneha Rana bowling stats", "S Rana bowling stats"),
    # Non-player text is untouched
    ("Top 5 run getters against Delhi Capitals", "Top 5 run getters against Delhi Capitals"),
    ("Mumbai Indians win percentage", "Mumbai Indians win percentage"),
]


def test_resolution():
    failures = [(q, exp, got) for q, exp in CASES if (got := resolve_player_names(q)) != exp]
    assert not failures, "\n".join(f"{q!r}: expected {e!r}, got {g!r}" for q, e, g in failures)


if __name__ == "__main__":
    test_alias_targets_exist()
    test_resolution()
    print(f"All name-resolution checks passed ({len(CASES)} cases).")
