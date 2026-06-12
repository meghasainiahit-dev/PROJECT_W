from django.shortcuts import render
from django.http import JsonResponse
# baaki logic wahi jo pehle diya

def dashboard(request):
    return render(request, "inventory/dashboard.html")