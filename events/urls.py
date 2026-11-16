from rest_framework.routers import SimpleRouter

from .views import EventViewSet

app_name = "events"

router = SimpleRouter()
router.register("events", EventViewSet, basename="event")

urlpatterns = router.urls
