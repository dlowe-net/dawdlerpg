from django.contrib import admin
from django.urls import path
from dawdle import views


app_name = 'dawdle'
urlpatterns = [
    path('', views.FrontView.as_view(), name='front'),
    path('about', views.AboutView.as_view(), name='about'),
    path('map', views.MapView.as_view(), name='map'),
    path('map/<path:player>', views.MapView.as_view(), name='player-map'),
    path('map/quest', views.MapView.as_view(), {'quest': 'quest'}, name='quest-map'),
    path('players', views.PlayerListView.as_view(), name='player-list'),
    path('player/<path:pk>', views.PlayerDetailView.as_view(), name='player-detail'),
    path('quest', views.QuestView.as_view(), name='quest'),
]
