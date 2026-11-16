"""The Ask Genie tab: a chat with the Genie agent Retail KPI Assistant, through the Genie Conversation API.

The REST calls go through a `do(method, path, body=None)` function (the Databricks SDK's API client in the app),
so this module is standard library only and its logic can be tested without a connection.
See doc/sales_dashboard.md, "Ask Genie tab", and doc/kpi_genie.md.
"""

API = "/api/2.0/genie/spaces"
TERMINAL = ("COMPLETED", "FAILED", "CANCELLED")
TIMEOUT_SECONDS = 180  # Genie answers in about 10-60 s; give up after this
MAX_ROWS = 50  # rows of a result shown in the chat

# The agent's sample questions (agents/kpi_genie/src/kpi_genie.json; a test keeps them the same).
SAMPLE_QUESTIONS = (
    "What does Conversion mean and how is it calculated?",
    "What are the top 10 stores by revenue?",
    "What is the conversion rate by channel?",
    "Who are our top clients by total spent?",
    "Do visitors spend more per basket than local clients?",
)

# What the user reads while Genie works, by message status.
STATUS_TEXT = {
    "SUBMITTED": "Question sent",
    "FILTERING_CONTEXT": "Reading the KPI definitions",
    "FETCHING_METADATA": "Reading the KPI definitions",
    "ASKING_AI": "Working out the answer",
    "PENDING_WAREHOUSE": "Waking up the SQL warehouse",
    "EXECUTING_QUERY": "Running the query",
    "COMPLETED": "Answered",
    "FAILED": "Failed",
    "CANCELLED": "Cancelled",
}


class GenieClient:
    """Start a conversation, ask follow-ups, read a message and its query result."""

    def __init__(self, space_id, do):
        if not space_id:
            raise ValueError("no Genie space id: set GENIE_SPACE_ID (the app's genie-space resource)")
        self.space_id, self.do = space_id, do

    def ask(self, question, conversation_id=None):
        """Send a question: a new conversation, or a follow-up in an existing one. Returns (conversation, message)."""
        question = (question or "").strip()
        if not question:
            raise ValueError("empty question")
        if conversation_id:
            r = self.do("POST", f"{API}/{self.space_id}/conversations/{conversation_id}/messages",
                        body={"content": question})
            return conversation_id, r.get("message_id") or r.get("id")
        r = self.do("POST", f"{API}/{self.space_id}/start-conversation", body={"content": question})
        return r["conversation_id"], r["message_id"]

    def message(self, conversation_id, message_id):
        return self.do("GET", f"{API}/{self.space_id}/conversations/{conversation_id}/messages/{message_id}")

    def query_result(self, conversation_id, message_id, attachment_id):
        return self.do("GET", f"{API}/{self.space_id}/conversations/{conversation_id}/messages/{message_id}"
                              f"/attachments/{attachment_id}/query-result")


def parse_message(msg):
    """The parts of a Genie message the chat shows: status, text, SQL and its description, the query attachment
    to fetch the rows from, suggested follow-up questions, and the error if it failed."""
    out = {"status": msg.get("status", "SUBMITTED"), "text": "", "sql": "", "description": "",
           "attachment_id": None, "suggested": [], "error": ""}
    texts = []
    for att in msg.get("attachments") or []:
        if att.get("text"):
            texts.append(att["text"].get("content", ""))
        if att.get("query"):
            out["sql"] = att["query"].get("query", "")
            out["description"] = att["query"].get("description", "")
            out["attachment_id"] = att.get("attachment_id") or att.get("id")
        if att.get("suggested_questions"):
            out["suggested"] = list(att["suggested_questions"].get("questions") or [])
    out["text"] = "\n\n".join(t for t in texts if t)
    error = msg.get("error") or {}
    out["error"] = error.get("error", "") if isinstance(error, dict) else str(error)
    return out


def fmt_value(value):
    """A result cell for an executive reader: grouped thousands, two decimals, small ratios with four."""
    if value is None:
        return ""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if number.is_integer() and abs(number) < 1e15:
        return f"{int(number):,}"
    if abs(number) < 1:
        return f"{number:.4f}"
    return f"{number:,.2f}"


def result_table(result, max_rows=MAX_ROWS):
    """(column names, rows as dicts of formatted values, total row count) of a query result."""
    statement = (result or {}).get("statement_response") or result or {}
    columns = [c["name"] for c in ((statement.get("manifest") or {}).get("schema") or {}).get("columns") or []]
    data = ((statement.get("result") or {}).get("data_array")) or []
    rows = [{c: fmt_value(v) for c, v in zip(columns, row)} for row in data[:max_rows]]
    return columns, rows, len(data)
