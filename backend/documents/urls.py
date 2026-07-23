from rest_framework.routers import DefaultRouter

from .views import (
    DocumentViewSet,
    FolderPermissionViewSet,
    FolderViewSet,
    FormTemplateViewSet,
)

router = DefaultRouter()
router.register("folders", FolderViewSet, basename="folder")
router.register("folder-permissions", FolderPermissionViewSet, basename="folderpermission")
router.register("documents", DocumentViewSet, basename="document")
router.register("form-templates", FormTemplateViewSet)

urlpatterns = router.urls
