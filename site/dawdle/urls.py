from django.contrib import admin
from django.urls import path
from dawdle import views


app_name = 'dawdle'
urlpatterns = [
    path('', views.PlayerListView.as_view(), name='player-list'),
    path('player/<slug:pk>', views.PlayerDetailView.as_view(), name='player-detail'),
]