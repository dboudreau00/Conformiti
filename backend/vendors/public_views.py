"""The vendor's side of the questionnaire: three endpoints keyed by the token
in the emailed link, no account needed.

Throttled per client on their own scope (THROTTLE_QUESTIONNAIRE): a token is
32 random bytes, so guessing is not a realistic threat, but a public endpoint
that writes deserves its own budget regardless.
"""
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import SimpleRateThrottle
from rest_framework.views import APIView

from . import questionnaire as q


class _QuestionnaireThrottle(SimpleRateThrottle):
    scope = "questionnaire"

    def get_cache_key(self, request, view):
        return self.cache_format % {"scope": self.scope, "ident": self.get_ident(request)}


class _Public(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [_QuestionnaireThrottle]

    @staticmethod
    def _refuse(exc):
        status = 404 if exc.code == "unknown" else 400
        return Response({"detail": exc.message, "code": exc.code}, status=status)


class QuestionnaireView(_Public):
    """GET: the questions, the vendor's draft and the link's state.
    PUT: save a draft."""

    def get(self, request, token):
        invite = q.find(token)
        if invite is None:
            return Response({"detail": "This questionnaire link is not valid.", "code": "unknown"}, status=404)
        return Response(q.public_state(invite, request))

    def put(self, request, token):
        invite = q.find(token)
        try:
            q.save_draft(invite, request.data.get("answers"), request)
        except q.QuestionnaireError as exc:
            return self._refuse(exc)
        return Response({"saved_at": invite.saved_at, "status": invite.status})


class QuestionnaireSubmitView(_Public):
    def post(self, request, token):
        invite = q.find(token)
        try:
            q.submit(invite, request.data.get("answers"), request.data.get("respondent_name"),
                     request.data.get("respondent_title", ""), request)
        except q.QuestionnaireError as exc:
            return self._refuse(exc)
        return Response({"status": "submitted", "submitted_at": invite.submitted_at,
                         "vendor": invite.vendor.name})
