from rest_framework.routers import SimpleRouter

from .views import EventViewSet, RegistrationViewSet

app_name = "events"

router = SimpleRouter()
router.register("events", EventViewSet, basename="event")
router.register("registrations", RegistrationViewSet, basename="registration")

urlpatterns = router.urls
