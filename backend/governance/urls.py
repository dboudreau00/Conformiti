from rest_framework.routers import DefaultRouter

from .views import (
    AccessReviewItemViewSet,
    AccessReviewViewSet,
    ChampionGroupViewSet,
    GroupMemberViewSet,
    MeetingMinuteViewSet,
    MeetingSeriesViewSet,
    RiskNoteViewSet,
    RiskViewSet,
)

router = DefaultRouter()
router.register("access-reviews", AccessReviewViewSet)
router.register("access-review-items", AccessReviewItemViewSet)
router.register("meeting-series", MeetingSeriesViewSet)
router.register("meeting-minutes", MeetingMinuteViewSet)
router.register("champion-groups", ChampionGroupViewSet)
router.register("group-members", GroupMemberViewSet)
router.register("risks", RiskViewSet, basename="risk")
router.register("risk-notes", RiskNoteViewSet, basename="risknote")

urlpatterns = router.urls
