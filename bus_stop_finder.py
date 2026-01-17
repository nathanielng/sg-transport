#!/usr/bin/env python3
"""
Bus Stop Finder - Singapore LTA DataMall API Tool

A comprehensive command-line tool for finding bus stops and checking real-time
bus arrivals in Singapore using the LTA DataMall API.

Features:
    - Real-time bus arrival information with load indicators
    - Find nearby bus stops based on location (GPS, IP, or coordinates)
    - Search bus stops by code or road name
    - Automatic location detection (IP-based or advanced GPS/WiFi triangulation)
    - Smart caching system (24-hour cache for bus stop data)
    - Comprehensive error handling and logging

Usage:
    # Check bus arrivals at a specific stop
    python bus_stop_finder.py --bus-stop 13011
    
    # Search for bus stop details
    python bus_stop_finder.py --search-stop 13011
    
    # Find stops on a road
    python bus_stop_finder.py --search-road "Orchard"
    
    # Find nearby stops using current location
    python bus_stop_finder.py
    
    # Find nearby stops with GPS
    python bus_stop_finder.py --gps --radius 1.0
    
    # Find nearby stops at specific coordinates
    python bus_stop_finder.py --lat 1.2834 --lon 103.8607

Requirements:
    - requests: HTTP library for API calls
    - python-dotenv: Environment variable management
    - geocoder (optional): Advanced GPS/WiFi location detection
    
Environment Variables:
    LTA_API_KEY: Your LTA DataMall API key (required)
    
API Documentation:
    https://datamall.lta.gov.sg/content/datamall/en/dynamic-data.html

Author: Singapore Bus Stop Finder
License: MIT
"""

import argparse
import json
import logging
import os
import requests

from pathlib import Path
from datetime import datetime, timedelta
from math import radians, cos, sin, sqrt, atan2
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# Load and validate API key at startup
LTA_API_KEY = os.getenv('LTA_API_KEY')
if not LTA_API_KEY:
    raise ValueError("LTA_API_KEY not found in environment variables. Please set it in your .env file.")
else:
    masked_key = f"{LTA_API_KEY[:4]}...{LTA_API_KEY[-4:]}" if len(LTA_API_KEY) > 8 else "***"
    logging.info(f"Using API key: {masked_key}")

# Cache configuration
DATA_DIR = Path("data")
CACHE_FILE = DATA_DIR / "bus_stops_cache.json"
CACHE_EXPIRY_HOURS = 24  # Cache expires after 24 hours

# Ensure data directory exists
DATA_DIR.mkdir(exist_ok=True)

def haversine_distance(lat1, lon1, lat2, lon2):
    """
    Calculate the distance between two points on Earth using the Haversine formula.
    Returns distance in kilometers.
    """
    R = 6371  # Earth's radius in kilometers
    
    lat1_rad, lon1_rad = radians(lat1), radians(lon1)
    lat2_rad, lon2_rad = radians(lat2), radians(lon2)
    
    dlat = lat2_rad - lat1_rad
    dlon = lon2_rad - lon1_rad
    
    a = sin(dlat / 2)**2 + cos(lat1_rad) * cos(lat2_rad) * sin(dlon / 2)**2
    c = 2 * atan2(sqrt(a), sqrt(1 - a))
    
    return R * c

def get_current_location():
    """
    Attempt to get the user's current location using IP geolocation.
    This provides approximate location based on IP address.
    Returns (latitude, longitude) tuple or None if unable to determine.
    
    Note: This is approximate and may not work behind VPNs or corporate networks.
    For mobile apps, you'd want to use device GPS instead.
    """
    try:
        logging.info("Attempting to detect your location...")
        response = requests.get('http://ip-api.com/json/', timeout=5)
        if response.status_code == 200:
            data = response.json()
            if data.get('status') == 'success':
                lat = data.get('lat')
                lon = data.get('lon')
                city = data.get('city', 'Unknown')
                country = data.get('country', 'Unknown')
                logging.info(f"Location detected: {city}, {country} ({lat}, {lon})")
                return lat, lon
    except Exception as e:
        logging.warning(f"Could not detect location: {e}")
    
    return None

def get_gps_location():
    """
    Get more accurate location using geocoder library with multiple providers.
    This uses WiFi/cell tower triangulation and other methods for better accuracy.
    Returns (latitude, longitude) tuple or None if unable to determine.
    
    Note: Requires 'geocoder' package. Install with: pip install geocoder
    """
    try:
        # Lazy import - only load when this function is called
        import geocoder
        
        logging.info("Attempting to detect your location using GPS/WiFi triangulation...")
        
        # Try multiple providers in order of preference
        providers = [
            ('ip', 'me'),  # Uses multiple IP geolocation services
            ('google', 'me'),  # Google's geolocation API (WiFi/cell towers)
            ('osm', 'me'),  # OpenStreetMap Nominatim
        ]
        
        for provider, query in providers:
            try:
                logging.info(f"Trying {provider} provider...")
                g = geocoder.get(query, method=provider)
                
                if g.ok and g.latlng:
                    lat, lon = g.latlng
                    address = g.address or 'Unknown location'
                    logging.info(f"Location detected via {provider}: {address} ({lat}, {lon})")
                    logging.info(f"Accuracy: {g.accuracy if hasattr(g, 'accuracy') else 'Unknown'}")
                    return lat, lon
            except Exception as e:
                logging.debug(f"{provider} provider failed: {e}")
                continue
        
        logging.warning("All GPS providers failed")
        return None
        
    except ImportError:
        logging.error("geocoder library not installed. Install with: pip install geocoder")
        logging.info("Falling back to basic IP geolocation...")
        return None
    except Exception as e:
        logging.warning(f"Could not detect GPS location: {e}")
        return None

def is_cache_valid():
    """
    Check if the cache file exists and is still valid (not expired).
    """
    if not CACHE_FILE.exists():
        return False
    
    try:
        with open(CACHE_FILE, 'r') as f:
            cache_data = json.load(f)
            cached_time = datetime.fromisoformat(cache_data.get('cached_at', ''))
            expiry_time = cached_time + timedelta(hours=CACHE_EXPIRY_HOURS)
            
            if datetime.now() < expiry_time:
                logging.info(f"Using cached bus stops (cached at {cached_time.strftime('%Y-%m-%d %H:%M:%S')})")
                return True
            else:
                logging.info("Cache expired, will fetch fresh data")
                return False
    except Exception as e:
        logging.warning(f"Error reading cache: {e}")
        return False

def load_bus_stops_from_cache():
    """
    Load bus stops from the cache file.
    """
    with open(CACHE_FILE, 'r') as f:
        cache_data = json.load(f)
        return cache_data.get('bus_stops', [])

def save_bus_stops_to_cache(bus_stops):
    """
    Save bus stops to the cache file with timestamp.
    """
    cache_data = {
        'cached_at': datetime.now().isoformat(),
        'total_stops': len(bus_stops),
        'bus_stops': bus_stops
    }
    
    with open(CACHE_FILE, 'w') as f:
        json.dump(cache_data, f)
    
    logging.info(f"Saved {len(bus_stops)} bus stops to cache: {CACHE_FILE}")

def fetch_all_bus_stops_from_api():
    """
    Fetch all bus stops from LTA DataMall API.
    API returns paginated results with $skip parameter.
    """
    url = "https://datamall2.mytransport.sg/ltaodataservice/BusStops"
    headers = {"accountKey": LTA_API_KEY}
    
    all_stops = []
    skip = 0
    
    logging.info("Fetching bus stops from LTA DataMall API...")
    
    while True:
        params = {"$skip": skip}
        response = requests.get(url, headers=headers, params=params)
        response.raise_for_status()
        
        data = response.json()
        stops = data.get("value", [])
        
        if not stops:
            break
        
        all_stops.extend(stops)
        skip += len(stops)
        logging.info(f"Fetched {len(all_stops)} bus stops so far...")
    
    logging.info(f"Total bus stops fetched: {len(all_stops)}")
    return all_stops

def get_all_bus_stops(use_cache=True):
    """
    Get all bus stops, either from cache or by fetching from API.
    
    Args:
        use_cache: If True, use cached data if available and valid.
                   If False, always fetch fresh data from API.
    
    Returns:
        List of all bus stops
    """
    if use_cache and is_cache_valid():
        return load_bus_stops_from_cache()
    
    # Fetch from API
    bus_stops = fetch_all_bus_stops_from_api()
    
    # Save to cache
    save_bus_stops_to_cache(bus_stops)
    
    return bus_stops

def get_bus_arrival(bus_stop_code, service_no=None):
    """
    Fetch bus arrival times from LTA DataMall API.
    
    Args:
        bus_stop_code: The bus stop code to query
        service_no: Optional specific bus service number to filter
    
    Returns:
        Dictionary containing bus arrival data, or None if error
    """
    url = "https://datamall2.mytransport.sg/ltaodataservice/v3/BusArrival"
    
    headers = {"AccountKey": LTA_API_KEY}
    params = {"BusStopCode": bus_stop_code}
    if service_no:
        params["ServiceNo"] = service_no
    
    try:
        response = requests.get(url, headers=headers, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        logging.debug(f"Bus arrival data retrieved for stop {bus_stop_code}")
        return data
    except requests.exceptions.RequestException as e:
        logging.error(f"Error fetching bus arrivals: {e}")
        return None
    except ValueError as e:
        logging.error(f"Error parsing bus arrival response: {e}")
        return None

def get_bus_stop_by_code(bus_stop_code, use_cache=True):
    """
    Get a specific bus stop by its code.
    
    Args:
        bus_stop_code: The bus stop code to search for
        use_cache: If True, use cached bus stop data if available
    
    Returns:
        Bus stop dictionary if found, None otherwise
    """
    all_stops = get_all_bus_stops(use_cache=use_cache)
    
    for stop in all_stops:
        if stop['BusStopCode'] == bus_stop_code:
            return {
                'BusStopCode': stop['BusStopCode'],
                'RoadName': stop['RoadName'],
                'Description': stop['Description'],
                'Latitude': float(stop['Latitude']),
                'Longitude': float(stop['Longitude'])
            }
    
    return None

def search_bus_stops_by_road(road_name, use_cache=True):
    """
    Search for bus stops by road name (case-insensitive partial match).
    
    Args:
        road_name: Road name or partial road name to search for
        use_cache: If True, use cached bus stop data if available
    
    Returns:
        List of matching bus stops sorted by bus stop code
    """
    all_stops = get_all_bus_stops(use_cache=use_cache)
    matching_stops = []
    
    search_term = road_name.lower()
    
    for stop in all_stops:
        if search_term in stop['RoadName'].lower():
            matching_stops.append({
                'BusStopCode': stop['BusStopCode'],
                'RoadName': stop['RoadName'],
                'Description': stop['Description'],
                'Latitude': float(stop['Latitude']),
                'Longitude': float(stop['Longitude'])
            })
    
    # Sort by bus stop code
    matching_stops.sort(key=lambda x: x['BusStopCode'])
    
    return matching_stops

def display_bus_stop_details(bus_stop):
    """
    Display detailed information about a single bus stop.
    """
    if not bus_stop:
        print("\nBus stop not found.\n")
        return
    
    print("\n" + "="*80)
    print("Bus Stop Details")
    print("="*80)
    print(f"Code:        {bus_stop['BusStopCode']}")
    print(f"Description: {bus_stop['Description']}")
    print(f"Road Name:   {bus_stop['RoadName']}")
    print(f"Latitude:    {bus_stop['Latitude']}")
    print(f"Longitude:   {bus_stop['Longitude']}")
    print("="*80 + "\n")

def display_road_search_results(road_name, bus_stops):
    """
    Display search results for bus stops on a road.
    """
    if not bus_stops:
        print(f"\nNo bus stops found on '{road_name}'.\n")
        return
    
    print("\n" + "="*80)
    print(f"Bus Stops on '{road_name}' ({len(bus_stops)} found)")
    print("="*80)
    print(f"{'Code':<8} {'Description':<50} {'Road Name':<20}")
    print("-"*80)
    
    for stop in bus_stops:
        code = stop['BusStopCode']
        desc = stop['Description'][:49]
        road = stop['RoadName'][:19]
        
        print(f"{code:<8} {desc:<50} {road:<20}")
    
    print("="*80)
    print(f"\nTotal: {len(bus_stops)} bus stops found\n")

def find_nearby_bus_stops(latitude, longitude, radius_km=0.5, use_cache=True):
    """
    Find bus stops within the specified radius of the given coordinates.
    
    Args:
        latitude: Latitude of the location
        longitude: Longitude of the location
        radius_km: Search radius in kilometers (default: 0.5km)
        use_cache: If True, use cached bus stop data if available
    
    Returns:
        List of nearby bus stops sorted by distance
    """
    all_stops = get_all_bus_stops(use_cache=use_cache)
    nearby_stops = []
    
    logging.info(f"Searching for bus stops within {radius_km}km of ({latitude}, {longitude})...")
    
    for stop in all_stops:
        stop_lat = float(stop['Latitude'])
        stop_lon = float(stop['Longitude'])
        
        distance = haversine_distance(latitude, longitude, stop_lat, stop_lon)
        
        if distance <= radius_km:
            nearby_stops.append({
                'BusStopCode': stop['BusStopCode'],
                'RoadName': stop['RoadName'],
                'Description': stop['Description'],
                'Latitude': stop_lat,
                'Longitude': stop_lon,
                'Distance': round(distance * 1000)  # Convert to meters
            })
    
    # Sort by distance
    nearby_stops.sort(key=lambda x: x['Distance'])
    
    logging.info(f"Found {len(nearby_stops)} bus stops within {radius_km}km")
    return nearby_stops

def display_bus_stops(bus_stops):
    """
    Display the list of nearby bus stops in a readable format.
    """
    if not bus_stops:
        logging.info("No bus stops found in the specified area.")
        return
    
    print("\n" + "="*80)
    print(f"{'Code':<8} {'Road Name':<25} {'Description':<30} {'Distance (m)':<12}")
    print("="*80)
    
    for stop in bus_stops:
        code = stop['BusStopCode']
        road = stop['RoadName'][:24]
        desc = stop['Description'][:29]
        dist = stop['Distance']
        
        print(f"{code:<8} {road:<25} {desc:<30} {dist:<12}")
    
    print("="*80)
    print(f"\nTotal: {len(bus_stops)} bus stops found\n")

def format_arrival_time(estimated_arrival):
    """
    Format the estimated arrival time into a human-readable string.
    Returns minutes until arrival or 'Arriving' if less than 1 minute.
    """
    if not estimated_arrival or estimated_arrival == "":
        return "N/A"
    
    try:
        arrival_time = datetime.fromisoformat(estimated_arrival.replace('Z', '+00:00'))
        now = datetime.now(arrival_time.tzinfo)
        diff = (arrival_time - now).total_seconds() / 60
        
        if diff < 1:
            return "Arriving"
        else:
            return f"{int(diff)} min"
    except Exception as e:
        logging.debug(f"Error parsing arrival time: {e}")
        return "N/A"

def get_load_indicator(load):
    """
    Convert load status to a visual indicator.
    SEA = Seats Available, SDA = Standing Available, LSD = Limited Standing
    """
    load_map = {
        'SEA': '🟢 Seats',
        'SDA': '🟡 Standing',
        'LSD': '🔴 Limited'
    }
    return load_map.get(load, load or 'N/A')

def display_bus_arrivals(bus_stop_code, arrival_data):
    """
    Display bus arrival times for a specific bus stop in a readable format.
    """
    if not arrival_data:
        logging.error(f"No arrival data available for bus stop {bus_stop_code}")
        return
    
    services = arrival_data.get('Services', [])
    
    if not services:
        print(f"\nNo buses currently serving bus stop {bus_stop_code}\n")
        return
    
    # Get bus stop metadata from arrival data
    bus_stop_code = arrival_data.get('BusStopCode', bus_stop_code)
    
    # Try to get bus stop details for description
    try:
        bus_stop_info = get_bus_stop_by_code(bus_stop_code, use_cache=True)
        if bus_stop_info:
            description = bus_stop_info.get('Description', '')
            road_name = bus_stop_info.get('RoadName', '')
            stop_header = f"Bus Stop: {bus_stop_code} - {description}"
            if road_name:
                stop_header += f" ({road_name})"
        else:
            stop_header = f"Bus Stop: {bus_stop_code}"
    except Exception as e:
        logging.debug(f"Could not fetch bus stop details: {e}")
        stop_header = f"Bus Stop: {bus_stop_code}"
    
    # Display bus stop info
    print("\n" + "="*90)
    print(stop_header)
    print("="*90)
    print(f"{'Bus':<8} {'Next Bus':<12} {'Load':<18} {'2nd Bus':<12} {'3rd Bus':<12}")
    print("-"*90)
    
    for service in services:
        bus_no = service.get('ServiceNo', 'N/A')
        
        # Next bus
        next_bus = service.get('NextBus', {})
        next_arrival = format_arrival_time(next_bus.get('EstimatedArrival'))
        next_load = get_load_indicator(next_bus.get('Load'))
        
        # Second bus
        next_bus_2 = service.get('NextBus2', {})
        arrival_2 = format_arrival_time(next_bus_2.get('EstimatedArrival'))
        
        # Third bus
        next_bus_3 = service.get('NextBus3', {})
        arrival_3 = format_arrival_time(next_bus_3.get('EstimatedArrival'))
        
        print(f"{bus_no:<8} {next_arrival:<12} {next_load:<18} {arrival_2:<12} {arrival_3:<12}")
    
    print("="*90)
    print(f"\nTotal: {len(services)} bus services")
    print("Legend: 🟢 Seats Available | 🟡 Standing Available | 🔴 Limited Standing\n")


def parse_arguments():
    """
    Parse command line arguments.
    """
    parser = argparse.ArgumentParser(
        description='Find nearby bus stops in Singapore',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s                           # Use current location (IP-based)
  %(prog)s --bus-stop 13011          # Check arrivals at stop 13011
  %(prog)s --search-stop 13011       # Show details for stop 13011
  %(prog)s --search-road "Orchard"   # Find all stops on Orchard Road
  %(prog)s --lat 1.2834 --lon 103.8607  # Use specific coordinates
  %(prog)s --radius 1.0              # Search within 1km radius
  %(prog)s --no-cache                # Force fresh data from API
  %(prog)s --gps                     # Use advanced GPS detection
        """
    )
    
    parser.add_argument(
        '--bus-stop', '-b',
        type=str,
        help='Bus stop code to check arrivals (e.g., 13011)'
    )
    
    parser.add_argument(
        '--search-stop', '-s',
        type=str,
        help='Search for bus stop details by code (e.g., 13011)'
    )
    
    parser.add_argument(
        '--search-road', '-r',
        type=str,
        help='Search for bus stops by road name (e.g., "Orchard Road")'
    )
    
    parser.add_argument(
        '--lat',
        type=float,
        help='Latitude of the location'
    )
    
    parser.add_argument(
        '--lon',
        type=float,
        help='Longitude of the location'
    )
    
    parser.add_argument(
        '--radius',
        type=float,
        default=0.5,
        help='Search radius in kilometers (default: 0.5)'
    )
    
    parser.add_argument(
        '--no-cache',
        action='store_true',
        help='Force fetch fresh data from API instead of using cache'
    )
    
    parser.add_argument(
        '--gps',
        action='store_true',
        help='Use advanced GPS/WiFi triangulation for better location accuracy (requires geocoder library)'
    )
    
    return parser.parse_args()

if __name__ == "__main__":
    logging.info("Starting nearby bus stops finder...")
    
    try:
        # Parse command line arguments
        args = parse_arguments()
        use_cache = not args.no_cache
        
        # Handle search operations first
        if args.search_stop:
            # Search for bus stop details by code
            logging.info(f"Searching for bus stop: {args.search_stop}")
            bus_stop = get_bus_stop_by_code(args.search_stop, use_cache=use_cache)
            display_bus_stop_details(bus_stop)
            
        elif args.search_road:
            # Search for bus stops by road name
            logging.info(f"Searching for bus stops on: {args.search_road}")
            bus_stops = search_bus_stops_by_road(args.search_road, use_cache=use_cache)
            display_road_search_results(args.search_road, bus_stops)
            
        elif args.bus_stop:
            # Display bus arrival times for the specified bus stop
            logging.info(f"Fetching bus arrivals for bus stop: {args.bus_stop}")
            
            arrival_data = get_bus_arrival(args.bus_stop)
            display_bus_arrivals(args.bus_stop, arrival_data)
            
        elif args.lat and args.lon:
            # Use provided coordinates
            target_latitude = args.lat
            target_longitude = args.lon
            logging.info(f"Using provided coordinates: ({target_latitude}, {target_longitude})")
            
            search_radius = args.radius
            
            # Find nearby bus stops
            nearby = find_nearby_bus_stops(
                target_latitude, 
                target_longitude, 
                search_radius,
                use_cache=use_cache
            )
            display_bus_stops(nearby)
            
        else:
            # Try to detect current location
            if args.gps:
                # Use advanced GPS detection
                location = get_gps_location()
                if not location:
                    logging.info("GPS detection failed, falling back to IP geolocation...")
                    location = get_current_location()
            else:
                # Use basic IP geolocation
                location = get_current_location()
            
            if location:
                target_latitude, target_longitude = location
            else:
                # Fallback to default location (Marina Bay Sands)
                logging.info("Using default location: Marina Bay Sands")
                target_latitude = 1.2834
                target_longitude = 103.8607
        
            search_radius = args.radius
            
            # Find nearby bus stops
            nearby = find_nearby_bus_stops(
                target_latitude, 
                target_longitude, 
                search_radius,
                use_cache=use_cache
            )
            display_bus_stops(nearby)
        
    except Exception as e:
        logging.error(f"Error: {e}")
