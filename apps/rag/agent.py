"""
Investiq LangChain tool-calling agent.
"""
from __future__ import annotations

import logging
from typing import Generator

from django.conf import settings
from langchain.agents import AgentExecutor, create_tool_calling_agent
from langchain_community.chat_message_histories import SQLChatMessageHistory
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.runnables.history import RunnableWithMessageHistory
from langchain_openai import ChatOpenAI

from .chain import _docs_to_citation_dicts, _format_docs
from .prompts import AGENT_SYSTEM_PROMPT, USER_PROMPT_TEMPLATE
from .retriever import retrieve_context_docs
from .tools import make_all_tools

logger = logging.getLogger(__name__)

_GOAL_WRITING_TOOLS = {"save_investment_goal", "update_investment_goal"}


def _fetch_active_goal_card(user_id: int) -> dict | None:
    """Return the user's current active goal as a card-ready dict, or None."""
    from apps.goals.models import InvestmentGoal, RISK_TOLERANCE_CHOICES

    goal = (
        InvestmentGoal.objects.filter(user_id=user_id, is_active=True)
        .order_by("-created_at")
        .first()
    )
    if goal is None:
        return None

    risk_display = dict(RISK_TOLERANCE_CHOICES).get(goal.risk_tolerance, "") if goal.risk_tolerance else ""
    return {
        "id": goal.pk,
        "goal_description": goal.goal_description or "",
        "horizon_years": goal.horizon_years,
        "risk_tolerance": goal.risk_tolerance,
        "risk_tolerance_display": risk_display,
        "target_return_pct": goal.target_return_pct,
        "monthly_savings_eur": goal.monthly_savings_eur,
        "created_at": goal.created_at.isoformat(),
    }


def _get_chat_history(conversation_id: int) -> SQLChatMessageHistory:
    """Keyed by conversation pk, stored in data/memory.sqlite3 (separate from db.sqlite3)."""
    return SQLChatMessageHistory(
        session_id=str(conversation_id),
        connection_string=f"sqlite:///{settings.MEMORY_DB_PATH}",
    )


def create_investiq_agent(
    user_id: int,
    conversation_id: int,
    jurisdiction: str = "DE",
    goal_context: str = "",
) -> RunnableWithMessageHistory:
    """Return the agent with tools and memory wired in.

    {input} will contain the user question plus pre-retrieved context, so the
    agent answers from context and optionally calls tools for goal side-effects.
    """
    tools = make_all_tools(user_id=user_id, conversation_id=conversation_id)

    llm = ChatOpenAI(
        model=settings.OPENAI_MODEL,
        temperature=0.2,
        streaming=True,
        openai_api_key=settings.OPENAI_API_KEY,
    )

    # Plain .format() keeps {jurisdiction}/{goal_context} out of LangChain's
    # template parser, which would conflict with {input}/{agent_scratchpad}.
    system_content = AGENT_SYSTEM_PROMPT.format(
        jurisdiction=jurisdiction,
        goal_context=goal_context or "No investment goals set.",
    )

    prompt = ChatPromptTemplate.from_messages([
        ("system", system_content),
        MessagesPlaceholder("chat_history"),
        ("human", "{input}"),
        MessagesPlaceholder("agent_scratchpad"),
    ])

    agent = create_tool_calling_agent(llm, tools, prompt)

    executor = AgentExecutor(
        agent=agent,
        tools=tools,
        verbose=False,
        return_intermediate_steps=True,
        max_iterations=6,
        handle_parsing_errors=True,
    )

    return RunnableWithMessageHistory(
        executor,
        get_session_history=lambda sid: _get_chat_history(int(sid)),
        input_messages_key="input",
        history_messages_key="chat_history",
        output_messages_key="output",
    )


def stream_agent_response(
    user_message: str,
    conversation_id: int,
    user_id: int,
    jurisdiction: str = "DE",
    goal_context: str = "",
) -> Generator[dict, None, None]:
    """Retrieve → emit citations → run agent → emit tokens.

    Yields: {"type": "citations"}, {"type": "token"}, {"type": "done"}, {"type": "error"}
    """
    logger.info(
        "stream_agent_response: conversation=%d user=%d jurisdiction=%s",
        conversation_id, user_id, jurisdiction,
    )

    all_docs = retrieve_context_docs(user_message=user_message, jurisdiction=jurisdiction)
    yield {"type": "citations", "citations": _docs_to_citation_dicts(all_docs)}

    context = _format_docs(all_docs)
    prompt_text = USER_PROMPT_TEMPLATE.format(
        user_message=user_message,
        context=context,
        jurisdiction=jurisdiction,
        goal_context=goal_context or "No investment goals set.",
    )

    try:
        agent = create_investiq_agent(
            user_id=user_id,
            conversation_id=conversation_id,
            jurisdiction=jurisdiction,
            goal_context=goal_context,
        )
    except Exception as exc:
        logger.exception("Failed to build agent: %s", exc)
        yield {"type": "error", "message": f"Agent initialisation error: {exc}"}
        return

    config = {"configurable": {"session_id": str(conversation_id)}}
    final_output = ""

    try:
        for chunk in agent.stream({"input": prompt_text}, config=config):
            # Detect goal-writing tool completions so the UI can render a card.
            for step in chunk.get("steps", []) or []:
                tool_name = getattr(getattr(step, "action", None), "tool", None)
                if tool_name in _GOAL_WRITING_TOOLS:
                    card = _fetch_active_goal_card(user_id)
                    if card is not None:
                        yield {"type": "goal_card", "goal": card}

            # AgentExecutor yields step-level dicts; "output" is the final answer.
            if "output" in chunk:
                final_output = chunk["output"]
    except Exception as exc:
        logger.exception("Agent error for conversation=%d: %s", conversation_id, exc)
        yield {"type": "error", "message": f"Agent error: {exc}"}
        return

    for word in final_output.split(" "):
        if word:
            yield {"type": "token", "content": word + " "}

    yield {"type": "done"}
