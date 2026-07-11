"""Router (Part 10). Checks modes in exact order: synthesis → affirmation → forecast → standard."""
from db import store

from . import modes
from .classify import classify_query_type


def route(user_id, session_id, user_message):
    """Route one user message to the correct mode and return the response text."""
    store.get_or_create_session(session_id, user_id)     # applies 30-min expiry reset
    chart = store.get_user_chart(user_id)
    if chart is None:
        raise ValueError(f"No chart stored for user {user_id}. Build and save it first.")

    count = store.get_interaction_count(session_id)
    query_type = classify_query_type(user_message)

    # 1. Synthesis — pipeline-triggered every 7th interaction (not content-driven).
    if count > 0 and count % 7 == 0:
        return modes.handle_synthesis(user_id, session_id, chart)
    # 2. Affirmation
    if query_type == "affirmation":
        return modes.handle_affirmation(user_id, session_id, user_message, chart)
    # 3. Forecast
    if query_type == "forecast":
        return modes.handle_forecast(user_id, session_id, user_message, chart)
    # 4. Standard (thematic / timing / mixed)
    return modes.handle_standard(user_id, session_id, user_message, chart)
