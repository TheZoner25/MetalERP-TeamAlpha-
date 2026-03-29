from django.urls import path
from .views import delivery_statuses

urlpatterns = [
    path('delivery-statuses/', delivery_statuses),
]