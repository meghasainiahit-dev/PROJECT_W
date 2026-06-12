import sys, os

# Add project path
sys.path.insert(0, "/home/atwogroups/traders.testwebs.in")

# Set settings module
os.environ['DJANGO_SETTINGS_MODULE'] = 'store.settings'

# Import WSGI
from django.core.wsgi import get_wsgi_application
application = get_wsgi_application()
