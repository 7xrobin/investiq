"""
Lightweight serializers for the chat API (no DRF dependency — plain dicts).
"""
from __future__ import annotations

from .models import Citation, Conversation, Message


def serialize_citation(citation: Citation) -> dict:
    return citation.to_dict()


def serialize_message(message: Message) -> dict:
    return {
        "id": message.pk,
        "role": message.role,
        "content": message.content,
        "created_at": message.created_at.isoformat(),
        "citations": [serialize_citation(c) for c in message.citations.all()],
    }


def serialize_conversation(conversation: Conversation, include_messages: bool = False) -> dict:
    data = {
        "id": conversation.pk,
        "title": conversation.title or conversation.get_title_from_first_message(),
        "jurisdiction": conversation.jurisdiction,
        "created_at": conversation.created_at.isoformat(),
        "updated_at": conversation.updated_at.isoformat(),
    }
    if include_messages:
        data["messages"] = [
            serialize_message(m)
            for m in conversation.messages.prefetch_related("citations").all()
        ]
    return data
