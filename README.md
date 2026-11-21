# 🏏 WPL StatsBot

**AI-Powered Cricket Analytics for Women's Premier League**

Transform natural language questions into instant WPL cricket statistics! Ask "H Kaur batting stats" or "top 5 bowlers who dismissed S Mandhana most" and get beautifully formatted tables with accurate data.

![WPL StatsBot Demo](https://img.shields.io/badge/Status-Active-brightgreen) ![Python](https://img.shields.io/badge/Python-3.13+-blue) ![Streamlit](https://img.shields.io/badge/Streamlit-1.52+-red) ![License](https://img.shields.io/badge/License-MIT-yellow)

## ✨ Features

- **🤖 Natural Language Queries**: Ask questions in plain English
- **📊 Instant Statistics**: Player batting/bowling stats, team performance, head-to-head records
- **🎯 Accurate Data**: Powered by SQL database with real WPL match data
- **📱 User-Friendly Interface**: Clean Streamlit web app with player naming guide
- **⚡ Fast Responses**: AI-generated SQL queries with formatted results
- **🔍 Advanced Analytics**: Player vs player stats, top performers, team standings

## 🚀 Quick Start

### Prerequisites
- Python 3.13+
- Google AI API key (for Gemini)

### Installation

1. **Clone the repository**
   ```bash
   git clone https://github.com/analysthrishi/wplstatbot.git
   cd wplstatbot
   ```

2. **Install dependencies**
   ```bash
   # Using uv (recommended)
   uv sync

   # Or using pip
   pip install -r requirements.txt
   ```

3. **Set up environment variables**
   ```bash
   # Create .env file
   echo "GOOGLE_API_KEY=your_google_api_key_here" > .env
   ```

4. **Run the application**
   ```bash
   # Using uv
   uv run streamlit run app.py

   # Or using streamlit directly
   streamlit run app.py
   ```

5. **Open your browser** to `http://localhost:8501`

## ☁️ Deploying (Streamlit Community Cloud)

1. Push this repo to GitHub (`wpl.db` is committed, so the app has its data).
2. Go to [share.streamlit.io](https://share.streamlit.io), sign in with GitHub and click **Create app**.
3. Pick this repo, branch `main`, main file `app.py`. Under **Advanced settings**, choose Python 3.13.
4. In **Advanced settings → Secrets**, add:
   ```toml
   GOOGLE_API_KEY = "your_google_api_key_here"
   ```
5. Click **Deploy**.

Streamlit Cloud installs from `requirements.txt`. After changing dependencies, regenerate it from the lockfile:
```bash
uv export --no-hashes --format requirements-txt --no-dev --no-emit-project > requirements.txt
```

**Safeguards for a public app:** the database is opened read-only, only single `SELECT` queries are run, each browser session is limited to 20 questions, and answers are cached for an hour. Also set a usage quota on your Gemini API key in Google AI Studio / Cloud console.

## 📖 Usage

### Example Queries

| Query Type | Example | Output |
|------------|---------|--------|
| Player Stats | `"H Kaur batting stats"` | Player performance table |
| Team Stats | `"Mumbai Indians performance"` | Team standings |
| Top Performers | `"top run scorers in WPL"` | Leaderboard table |
| Head-to-Head | `"bowlers who dismissed S Mandhana most"` | Dismissal analysis |

### Player Naming Convention

Players are stored using **Initial(s) + Surname** format:

| Full Name | Database Name | Example |
|-----------|---------------|---------|
| Harmanpreet Kaur | `H Kaur` | `"H Kaur batting stats"` |
| Natalie Sciver-Brunt | `NR Sciver-Brunt` | `"NR Sciver-Brunt bowling stats"` |
| Ashleigh Gardner | `A Gardner` | `"A Gardner stats"` |
| Alyssa Healy | `AJ Healy` | `"AJ Healy batting stats"` |

**Pro Tips:**
- Use exact database names for best results
- Check the in-app player guide for popular players

## 🏗️ Architecture

```
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐
│   Streamlit UI  │───▶│  LangChain       │───▶│   SQLite DB     │
│                 │    │  SQL Generation  │    │   (WPL Data)    │
└─────────────────┘    └──────────────────┘    └─────────────────┘
                              │
                              ▼
                       ┌──────────────────┐
                       │   Google Gemini  │
                       │  Response Format │
                       └──────────────────┘
```

### Technology Stack

- **Frontend**: Streamlit - Interactive web interface
- **AI Engine**: Google Gemini 2.5 Flash-Lite - Natural language processing
- **Query Generation**: LangChain SQLDatabase - SQL query synthesis
- **Database**: SQLite - WPL cricket data storage
- **Data Processing**: Pandas - Data manipulation
- **Environment**: Python 3.13+ with uv for dependency management

### Database Schema

```sql
-- Core tables in wpl.db
balls          -- Ball-by-ball delivery data
matches        -- Match information and results
players        -- Player details and IDs
wickets        -- Dismissal information
teams          -- Team data
match_players  -- Which players played in each match
```

## 🔧 Development

### Project Structure
```
wplstatbot/
├── app.py               # Streamlit UI
├── chain.py             # Prompts + text-to-SQL chain (shared by app.py and test.py)
├── test.py              # Manual end-to-end check (calls the Gemini API)
├── loading.ipynb        # Builds wpl.db from the Cricsheet JSON files
├── wpl.db               # SQLite database
├── data/                # Cricsheet WPL match files (JSON)
├── requirements.txt     # Pinned dependencies (exported from uv.lock)
├── pyproject.toml       # Project configuration
├── .env                 # Environment variables (create yourself)
└── README.md            # This file
```

### Running Tests
```bash
# Test the AI query generation
uv run python test.py
```

### Contributing

1. Fork the repository
2. Create a feature branch: `git checkout -b feature-name`
3. Make your changes and test thoroughly
4. Commit: `git commit -m 'Add some feature'`
5. Push: `git push origin feature-name`
6. Open a Pull Request

## 📊 Sample Outputs

### Player Batting Stats
```
H Kaur has played 26 innings, scoring 851 runs in 593 balls at a strike rate of 143.51.

| Player | Innings | Runs | Balls | Strike Rate |
|--------|---------|------|-------|-------------|
| H Kaur | 26      | 851  | 593   | 143.51      |
```

### Team Standings
```
| Team             | Matches | Wins | Losses | Win % |
|------------------|---------|------|--------|-------|
| Mumbai Indians   | 29      | 20   | 9      | 68.97 |
| Delhi Capitals   | 27      | 17   | 10     | 62.96 |
```

## 🔒 Security & Privacy

- **API Keys**: Never commit `.env` files containing API keys
- **Database**: WPL data is publicly available cricket statistics
- **No User Data**: App doesn't collect or store user information

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🙏 Acknowledgments

- **WPL Data**: Ball-by-ball match data from [Cricsheet](https://cricsheet.org/)
- **LangChain**: For the powerful SQL database toolkit
- **Google AI**: For Gemini's excellent language understanding
- **Streamlit**: For making data apps accessible to everyone

## 📞 Support

- **Issues**: [GitHub Issues](https://github.com/analysthrishi/wplstatbot/issues)

---

**Made with ❤️ for cricket fans and data enthusiasts**

*Transforming cricket data into insights, one query at a time!* 🏏🤖