from rest_framework import serializers


class RouteRequestSerializer(serializers.Serializer):
    start = serializers.CharField(max_length=200, help_text="City, ST | address | lat,lon")
    finish = serializers.CharField(max_length=200, help_text="City, ST | address | lat,lon")
    vehicle_range = serializers.FloatField(default=500.0, min_value=50, max_value=1500)
    mpg = serializers.FloatField(default=10.0, min_value=1, max_value=100)
    full_geometry = serializers.BooleanField(default=False)
