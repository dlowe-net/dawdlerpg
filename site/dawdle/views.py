from django.shortcuts import render
from .models import Player, Item
from django.db.models import Sum
from django.views import generic

class FrontView(generic.TemplateView):
    template_name = "dawdle/front.html"

class AboutView(generic.TemplateView):
    template_name = "dawdle/about.html"

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
