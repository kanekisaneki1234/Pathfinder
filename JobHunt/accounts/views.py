from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect

from .forms import SignUpForm

def home(request):
    return render(request, "home.html")

def signup(request):
    if request.method == "POST":
        form = SignUpForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)  # auto-login after signup
            return redirect("profile")
    else:
        form = SignUpForm()
    return render(request, "signup.html", {"form": form})

@login_required
def profile(request):
    return render(request, "profile.html")

from .models import RoadmapStep
from django.contrib.auth.decorators import login_required

@login_required
def roadmap(request):
    steps = (
        RoadmapStep.objects
        .filter(user=request.user)
        .order_by("order")
    )

    return render(request, "roadmap.html", {
        "steps": steps
    })
