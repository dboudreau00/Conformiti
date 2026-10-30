from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import SimpleRateThrottle
from rest_framework.views import APIView

from accounts import tenancy

from . import questionnaire as q


class _QuestionnaireThrottle(SimpleRateThrottle):
    # Its own budget (THROTTLE_QUESTIONNAIRE): a public endpoint that writes needs one, token guessing aside.
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
    def get(self, request, token):
        invite = q.find(token)
        if invite is None:
            return Response({"detail": "This questionnaire link is not valid.", "code": "unknown"}, status=404)
        with tenancy.scoped(invite.workspace_id):
            return Response(q.public_state(invite, request))

    def put(self, request, token):
        invite = q.find(token)
        # No account on the link: rows are filed under the workspace that sent the questionnaire.
        with tenancy.scoped(invite.workspace_id if invite else None):
            try:
                q.save_draft(invite, request.data.get("answers"), request)
            except q.QuestionnaireError as exc:
                return self._refuse(exc)
        return Response({"saved_at": invite.saved_at, "status": invite.status})


class QuestionnaireSubmitView(_Public):
    def post(self, request, token):
        invite = q.find(token)
        with tenancy.scoped(invite.workspace_id if invite else None):
            try:
                q.submit(invite, request.data.get("answers"), request.data.get("respondent_name"),
                         request.data.get("respondent_title", ""), request)
            except q.QuestionnaireError as exc:
                return self._refuse(exc)
        return Response({"status": "submitted", "submitted_at": invite.submitted_at,
                         "vendor": invite.vendor.name})
