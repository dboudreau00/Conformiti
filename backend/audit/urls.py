from rest_framework.routers import DefaultRouter

from .views import AuditLogViewSet

router = DefaultRouter()
router.register("audit-log", AuditLogViewSet)

urlpatterns = router.urls
