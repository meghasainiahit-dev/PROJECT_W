from rest_framework.permissions import BasePermission

secret_key='Sm9pbl-SmoAtsqx-jzTIfEslmi-TLqHw95m-001' 

class IsAuthenticatedDelete(BasePermission):
    def has_permission(self, request, view):
        
        key = request.data.get('sec_pass_key')
        if key == secret_key:
            return True
        else :
            return False