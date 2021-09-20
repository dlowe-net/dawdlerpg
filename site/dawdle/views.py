import io
import os

from django.db.models import Sum
from django.http import HttpResponse
from django.shortcuts import render
from django.views import generic, View

from PIL import Image, ImageDraw

from .models import Player, Item, Quest
from project.settings import BASE_DIR

class FrontView(generic.TemplateView):
    template_name = "dawdle/front.html"


class AboutView(generic.TemplateView):
    template_name = "dawdle/about.html"


class MapView(View):

    def _colorplayer(self, player, questors):
        if questors and player.name in questors:
            return (0x00, 0xff, 0xe9), (0x80, 0xbb, 0xff)
        if player.online:
            return (0x00, 0x1e, 0xe9), (0x80, 0xbb, 0xff)
        return (0xaa, 0xaa, 0xaa), (0xee, 0xee, 0xee)


    def get(self, request, *args, **kwargs):
        base_map = Image.open(os.path.join(BASE_DIR, "dawdle/static/dawdle/map.png"))
        full_map = base_map.copy()
        draw = ImageDraw.Draw(full_map)

        q = Quest.objects.all()
        questors = None
        if q:
            q = q[0]
            questors = [q.p1, q.p2, q.p3, q.p4]
        if 'player' in kwargs:
            pquery = Player.objects.filter(name=kwargs['player'])
            dotsize = 5
        elif 'quest' in kwargs and q:
            pquery = Player.objects.filter(name__in=['rethion'])
        else:
            pquery = Player.objects
            dotsize = 3

        if q and q.mode == 2:
            if q.stage == 1:
                draw.ellipse([q.dest1x-dotsize, q.dest1y-dotsize, q.dest1x+dotsize, q.dest1y+dotsize], fill=(0xff, 0xff, 0x00))
            else:
                draw.ellipse([q.dest2x-dotsize, q.dest2y-dotsize, q.dest2x+dotsize, q.dest2y+dotsize], fill=(0xff, 0xff, 0x00))

        for p in pquery.all():
            fillcolor, strokecolor = self._colorplayer(p, questors)
            draw.ellipse([p.posx-dotsize, p.posy-dotsize, p.posx+dotsize, p.posy+dotsize],
                         outline=strokecolor,
                         fill=fillcolor)

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


class QuestView(generic.TemplateView):
    template_name = "dawdle/quest.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        try:
            quest = Quest.objects.get()
            questors = Player.objects.filter(name__in=[quest.p1,quest.p2,quest.p3,quest.p4]).all()
            context['quest'] = quest
            context['questors'] = questors
        except Quest.DoesNotExist:
            context['quest'] = None
        return context
