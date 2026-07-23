"""Jira integration endpoints. Configuration is manager-only; anyone signed in
can read the tracked boards and their issues (the whole point is visibility)."""
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import SAFE_METHODS, BasePermission, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .jira import JiraError, board_issues, verify
from .models import JiraBoard, JiraIntegration
from .serializers import JiraBoardSerializer, JiraConfigSerializer


class CanManageIntegrations(BasePermission):
    def has_permission(self, request, view):
        u = request.user
        return bool(u and u.is_authenticated and u.can_manage_users)


class ManageOrReadOnly(BasePermission):
    def has_permission(self, request, view):
        u = request.user
        if not (u and u.is_authenticated):
            return False
        return True if request.method in SAFE_METHODS else u.can_manage_users


class JiraConfigView(APIView):
    """GET/PATCH the single Jira configuration row (managers only)."""
    permission_classes = [CanManageIntegrations]

    def get(self, request):
        return Response(JiraConfigSerializer(JiraIntegration.get_solo()).data)

    def patch(self, request):
        config = JiraIntegration.get_solo()
        ser = JiraConfigSerializer(config, data=request.data, partial=True)
        ser.is_valid(raise_exception=True)
        ser.save()
        return Response(JiraConfigSerializer(config).data)


class JiraTestView(APIView):
    """POST — verify the saved credentials against Jira and report the result."""
    permission_classes = [CanManageIntegrations]

    def post(self, request):
        try:
            return Response({"detail": verify(JiraIntegration.get_solo())})
        except JiraError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)


class JiraBoardViewSet(viewsets.ModelViewSet):
    """Tracked boards. `issues` proxies the board's issues server-side so the
    API token never reaches the browser."""
    queryset = JiraBoard.objects.all()
    serializer_class = JiraBoardSerializer
    permission_classes = [ManageOrReadOnly]

    def perform_create(self, serializer):
        serializer.save(added_by=self.request.user)

    @action(detail=True, methods=["get"], permission_classes=[IsAuthenticated])
    def issues(self, request, pk=None):
        board = self.get_object()
        try:
            data = board_issues(JiraIntegration.get_solo(), board.board_id)
        except JiraError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)
        return Response(data)
