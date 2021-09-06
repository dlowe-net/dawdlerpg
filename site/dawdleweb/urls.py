from django.contrib import admin
from django.urls import path
from dawdleweb import views


app_name = 'dawdleweb'
urlpatterns = [
    path('', views.PlayerListView.as_view(), name='player-list'),
    path('player/<slug:pk>', views.PlayerDetailView.as_view(), name='player-detail'),
]
