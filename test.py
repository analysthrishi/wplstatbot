"""Manual end-to-end check of the text-to-SQL chain (makes real Gemini API calls)."""
import os

from dotenv import load_dotenv

from chain import build_chain, clean_sql

load_dotenv()
api_key = os.getenv("GOOGLE_API_KEY")

write_query, execute_query, chain = build_chain(api_key)

question = "top run scorers in wpl"
raw_query = write_query.invoke({"question": question})
cleaned_query = clean_sql(raw_query)
print("Generated SQL:", raw_query)
print("Cleaned SQL:", cleaned_query)
result = execute_query.invoke(cleaned_query)
print("Result:", result)
response = chain.invoke({"question": question})
print("Final Response:", response)
