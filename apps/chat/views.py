"""
Chat views:
  - ChatView          GET  /chat/            — render main UI
  - StreamView        POST /chat/stream/     — SSE streaming response
  - ConversationHistoryView GET /chat/history/<pk>/  — JSON history
"""
from __future__ import annotations

import json
import logging

from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import JsonResponse, StreamingHttpResponse
from django.shortcuts import get_object_or_404, render
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator

from apps.goals.models import InvestmentGoal
from apps.rag.agent import stream_agent_response

from .models import Citation, Conversation, Message
from .serializers import serialize_conversation

logger = logging.getLogger(__name__)


class ChatView(LoginRequiredMixin, View):
    """
    GET /chat/ — renders the main split-panel chat interface.

    Passes the list of existing conversations to the template so the UI can
    show conversation history in the sidebar.
    """

    template_name = "chat/index.html"

    def get(self, request):
        conversations = (
            Conversation.objects.filter(user=request.user)
            .order_by("-updated_at")[:50]
        )

        # Active investment goals for the goal summary widget.
        active_goal = (
            InvestmentGoal.objects.filter(user=request.user, is_active=True)
            .order_by("-created_at")
            .first()
        )

        # Current conversation from query param (or latest).
        conversation_id = request.GET.get("conversation_id")
        current_conversation = None
        if conversation_id:
            current_conversation = Conversation.objects.filter(
                pk=conversation_id, user=request.user
            ).first()

        return render(
            request,
            self.template_name,
            {
                "conversations": conversations,
                "current_conversation": current_conversation,
                "active_goal": active_goal,
                "jurisdiction_choices": [
                    ("DE", "Germany"),
                    ("EU", "EU"),
                    ("UK", "UK"),
                    ("US", "US"),
                ],
                "default_jurisdiction": request.user.preferred_jurisdiction,
            },
        )


@method_decorator(csrf_exempt, name="dispatch")
class StreamView(LoginRequiredMixin, View):
    """
    POST /chat/stream/ — Server-Sent Events streaming endpoint.

    Expected JSON body:
        {
            "message": "<user message>",
            "jurisdiction": "DE",          # optional, defaults to user preference
            "conversation_id": 42           # optional, creates new if absent
        }

    SSE event stream format:
        data: {"type": "token",     "content": "..."}
        data: {"type": "citations", "citations": [...]}
        data: {"type": "done"}
    """

    def post(self, request):
        try:
            body = json.loads(request.body)
        except (json.JSONDecodeError, ValueError):
            return JsonResponse({"error": "Invalid JSON body."}, status=400)

        user_message_text = body.get("message", "").strip()
        if not user_message_text:
            return JsonResponse({"error": "message field is required."}, status=400)

        jurisdiction = body.get("jurisdiction") or request.user.preferred_jurisdiction
        conversation_id = body.get("conversation_id")

        # Get or create conversation.
        if conversation_id:
            conversation = get_object_or_404(Conversation, pk=conversation_id, user=request.user)
        else:
            conversation = Conversation.objects.create(
                user=request.user,
                jurisdiction=jurisdiction,
            )

        # Persist user message immediately.
        user_message = Message.objects.create(
            conversation=conversation,
            role="user",
            content=user_message_text,
        )

        # Auto-title the conversation from the first message.
        if not conversation.title:
            conversation.title = user_message_text[:80]
            conversation.save(update_fields=["title"])

        # Retrieve active goal context string.
        active_goal = (
            InvestmentGoal.objects.filter(user=request.user, is_active=True)
            .order_by("-created_at")
            .first()
        )
        goal_context = active_goal.to_context_string() if active_goal else ""

        def event_stream():
            """Generator that yields SSE-formatted strings."""
            collected_tokens: list[str] = []
            collected_citations: list[dict] = []

            try:
                for chunk in stream_agent_response(
                    user_message=user_message_text,
                    conversation_id=conversation.pk,
                    user_id=request.user.pk,
                    jurisdiction=jurisdiction,
                    goal_context=goal_context,
                ):
                    chunk_type = chunk.get("type")

                    if chunk_type == "token":
                        collected_tokens.append(chunk["content"])
                        payload = json.dumps({"type": "token", "content": chunk["content"]})
                        yield f"data: {payload}\n\n"

                    elif chunk_type == "citations":
                        collected_citations = chunk.get("citations", [])
                        payload = json.dumps({"type": "citations", "citations": collected_citations})
                        yield f"data: {payload}\n\n"

                    elif chunk_type == "done":
                        # Persist the assistant message + citations.
                        full_response = "".join(collected_tokens)
                        assistant_message = Message.objects.create(
                            conversation=conversation,
                            role="assistant",
                            content=full_response,
                        )
                        for cit_data in collected_citations:
                            Citation.objects.create(
                                message=assistant_message,
                                source_title=cit_data.get("source_title", "Unknown"),
                                source_author=cit_data.get("source_author", ""),
                                source_year=cit_data.get("source_year"),
                                source_url=cit_data.get("source_url", ""),
                                source_type=cit_data.get("source_type", "regulatory"),
                                page_number=cit_data.get("page_number"),
                                jurisdiction=cit_data.get("jurisdiction", jurisdiction),
                                relevance_score=cit_data.get("relevance_score"),
                                chunk_text=cit_data.get("chunk_text", ""),
                            )
                        # Update conversation timestamp.
                        conversation.save(update_fields=["updated_at"])
                        payload = json.dumps({
                            "type": "done",
                            "conversation_id": conversation.pk,
                            "message_id": assistant_message.pk,
                        })
                        yield f"data: {payload}\n\n"

            except Exception as exc:
                logger.exception("Error during RAG streaming for conversation %s", conversation.pk)
                error_payload = json.dumps({"type": "error", "message": str(exc)})
                yield f"data: {error_payload}\n\n"

        response = StreamingHttpResponse(event_stream(), content_type="text/event-stream")
        response["Cache-Control"] = "no-cache"
        response["X-Accel-Buffering"] = "no"  # Disable Nginx buffering.
        return response


class ConversationHistoryView(LoginRequiredMixin, View):
    """
    GET /chat/history/<conversation_id>/ — returns full message history as JSON.
    """

    def get(self, request, conversation_id: int):
        conversation = get_object_or_404(Conversation, pk=conversation_id, user=request.user)
        data = serialize_conversation(conversation, include_messages=True)
        return JsonResponse(data)


class ConversationListView(LoginRequiredMixin, View):
    """
    GET /chat/conversations/ — returns paginated list of conversations as JSON.
    """

    def get(self, request):
        conversations = (
            Conversation.objects.filter(user=request.user)
            .order_by("-updated_at")[:50]
        )
        data = [serialize_conversation(c) for c in conversations]
        return JsonResponse({"conversations": data})
