import io
import os

from django.db.models import Sum
from django.http import HttpResponse
from django.shortcuts import render
from django.views import generic, View

from PIL import Image, ImageDraw

from .models import Player, Item
from project.settings import BASE_DIR

class FrontView(generic.TemplateView):
    template_name = "dawdle/front.html"


class AboutView(generic.TemplateView):
    template_name = "dawdle/about.html"


class MapView(View):

    def get(self, request, *args, **kwargs):
        base_map = Image.open(os.path.join(BASE_DIR, "dawdle/static/dawdle/map.png"))
        full_map = base_map.copy()
        draw = ImageDraw.Draw(full_map)
        if 'player' in kwargs:
            pquery = Player.objects.filter(name=kwargs['player'])
            dotsize = 3
        else:
            pquery = Player.objects
            dotsize = 1

        for p in pquery.all():
            color = (0xff, 0x00, 0x00) if p.online else (0xee, 0xee, 0xee)
            draw.ellipse([p.posx-dotsize, p.posy-dotsize, p.posx+dotsize, p.posy+dotsize], outline=color, fill=color)
        map_bytes = io.BytesIO()
        full_map.save(map_bytes, format="png")
        return HttpResponse(map_bytes.getvalue(), content_type='image/png')


class PlayerListView(generic.ListView):
    model = Player
    queryset = Player.objects.order_by('level', 'nextlvl')


class PlayerDetailView(generic.DetailView):
    model = Player


    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        p = self.object
        context['total_penalties'] = sum([p.penkick, p.penpart, p.penquit, p.pendropped, p.pennick, p.penmessage, p.penlogout, p.penquest])
        context['total_items'] = p.item_set.aggregate(Sum('level'))['level__sum']
        return context
