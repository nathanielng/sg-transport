"""
Bus Stop Finder - Lambda API handler

Exposes two routes via API Gateway (proxy integration):
    GET /nearby?lat=<float>&lon=<float>&radius=<km>   -> nearby bus stops
    GET /arrival?busStopCode=<code>                    -> real-time arrivals

The LTA DataMall API key stays server-side (Lambda env var), never shipped
to the browser. Bus stop list is cached in /tmp for the lifetime of the
execution environment to cut down on LTA API calls across warm invocations.
"""

import json
import logging
import os
import time
from math import radians, cos, sin, sqrt, atan2

import requests

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger()

LTA_API_KEY = os.environ["LTA_API_KEY"]
ALLOWED_ORIGIN = os.environ.get("ALLOWED_ORIGIN", "*")

CACHE_FILE = "/tmp/bus_stops_cache.json"
CACHE_TTL_SECONDS = 24 * 60 * 60

CORS_HEADERS = {
    "Access-Control-Allow-Origin": ALLOWED_ORIGIN,
    "Access-Control-Allow-Headers": "Content-Type,X-Api-Key",
    "Access-Control-Allow-Methods": "GET,OPTIONS",
}


def _response(status_code, body):
    return {
        "statusCode": status_code,
        "headers": {**CORS_HEADERS, "Content-Type": "application/json"},
        "body": json.dumps(body),
    }


def haversine_distance(lat1, lon1, lat2, lon2):
    r = 6371  # km
    lat1_rad, lon1_rad = radians(lat1), radians(lon1)
    lat2_rad, lon2_rad = radians(lat2), radians(lon2)
    dlat = lat2_rad - lat1_rad
    dlon = lon2_rad - lon1_rad
    a = sin(dlat / 2) ** 2 + cos(lat1_rad) * cos(lat2_rad) * sin(dlon / 2) ** 2
    return r * 2 * atan2(sqrt(a), sqrt(1 - a))


def fetch_all_bus_stops_from_api():
    url = "https://datamall2.mytransport.sg/ltaodataservice/BusStops"
    headers = {"AccountKey": LTA_API_KEY}

    all_stops = []
    skip = 0
    while True:
        response = requests.get(url, headers=headers, params={"$skip": skip}, timeout=10)
        response.raise_for_status()
        stops = response.json().get("value", [])
        if not stops:
            break
        all_stops.extend(stops)
        skip += len(stops)

    logger.info("Fetched %d bus stops from LTA", len(all_stops))
    return all_stops


def get_all_bus_stops():
    if os.path.exists(CACHE_FILE):
        age = time.time() - os.path.getmtime(CACHE_FILE)
        if age < CACHE_TTL_SECONDS:
            with open(CACHE_FILE) as f:
                return json.load(f)

    stops = fetch_all_bus_stops_from_api()
    with open(CACHE_FILE, "w") as f:
        json.dump(stops, f)
    return stops


def find_nearby_bus_stops(latitude, longitude, radius_km):
    nearby = []
    for stop in get_all_bus_stops():
        stop_lat = float(stop["Latitude"])
        stop_lon = float(stop["Longitude"])
        distance = haversine_distance(latitude, longitude, stop_lat, stop_lon)
        if distance <= radius_km:
            nearby.append(
                {
                    "BusStopCode": stop["BusStopCode"],
                    "RoadName": stop["RoadName"],
                    "Description": stop["Description"],
                    "Latitude": stop_lat,
                    "Longitude": stop_lon,
                    "Distance": round(distance * 1000),
                }
            )
    nearby.sort(key=lambda s: s["Distance"])
    return nearby


def get_bus_stop_by_code(bus_stop_code):
    for stop in get_all_bus_stops():
        if stop["BusStopCode"] == bus_stop_code:
            return {
                "BusStopCode": stop["BusStopCode"],
                "RoadName": stop["RoadName"],
                "Description": stop["Description"],
                "Latitude": float(stop["Latitude"]),
                "Longitude": float(stop["Longitude"]),
            }
    return None


def get_bus_arrival(bus_stop_code):
    url = "https://datamall2.mytransport.sg/ltaodataservice/v3/BusArrival"
    headers = {"AccountKey": LTA_API_KEY}
    response = requests.get(url, headers=headers, params={"BusStopCode": bus_stop_code}, timeout=10)
    response.raise_for_status()
    return response.json()


def handle_nearby(params):
    try:
        lat = float(params["lat"])
        lon = float(params["lon"])
    except (KeyError, TypeError, ValueError):
        return _response(400, {"error": "lat and lon query parameters are required numbers"})

    radius_km = float(params.get("radius", 0.5))
    radius_km = max(0.1, min(radius_km, 5.0))  # clamp to a sane range

    stops = find_nearby_bus_stops(lat, lon, radius_km)
    return _response(200, {"stops": stops})


def handle_arrival(params):
    bus_stop_code = params.get("busStopCode")
    if not bus_stop_code:
        return _response(400, {"error": "busStopCode query parameter is required"})

    data = get_bus_arrival(bus_stop_code)
    return _response(200, data)


def handle_stop(params):
    bus_stop_code = params.get("code")
    if not bus_stop_code:
        return _response(400, {"error": "code query parameter is required"})

    stop = get_bus_stop_by_code(bus_stop_code)
    if not stop:
        return _response(404, {"error": "bus stop not found"})
    return _response(200, stop)


def lambda_handler(event, context):
    method = event.get("httpMethod") or event.get("requestContext", {}).get("http", {}).get("method")
    if method == "OPTIONS":
        return _response(200, {})

    path = event.get("path") or event.get("rawPath") or ""
    params = event.get("queryStringParameters") or {}

    try:
        if path.endswith("/nearby"):
            return handle_nearby(params)
        if path.endswith("/arrival"):
            return handle_arrival(params)
        if path.endswith("/stop"):
            return handle_stop(params)
        return _response(404, {"error": "not found"})
    except requests.exceptions.RequestException as e:
        logger.error("LTA API error: %s", e)
        return _response(502, {"error": "upstream LTA API error"})
    except Exception as e:
        logger.exception("Unhandled error")
        return _response(500, {"error": "internal server error"})
