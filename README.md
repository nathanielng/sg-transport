# Bus Stop Finder

Tools for finding nearby bus stops and checking real-time bus arrivals in Singapore using the LTA DataMall API. This repo has two parts:

- **`bus_stop_finder.py`** — a command-line tool (IP/GPS-based location, local caching). See [CLI Tool](#cli-tool) below.
- **`frontend/` + `lambda/` + `template.yaml`** — a mobile-friendly web app that uses the browser's GPS via `navigator.geolocation`, backed by a serverless AWS Lambda + API Gateway API. See [Mobile Web App](#mobile-web-app-aws) below.

## Mobile Web App (AWS)

A static single-page app (`frontend/index.html`) that gets your location from the browser and calls a Lambda-backed API (`lambda/app.py`) which proxies LTA DataMall. The LTA API key stays server-side — the frontend never sees it.

### Features

- 📍 Browser geolocation (`navigator.geolocation`) — works on any mobile browser over HTTPS
- ⭐ **Favorites**: save bus stop codes to `localStorage` (device-local, never sent anywhere but the API), with auto-lookup of the stop's description as you type the code
- 🗺️ **Map view**: optional, lazy-loaded [Leaflet](https://leafletjs.com/) map with OpenStreetMap tiles — Leaflet's JS/CSS only load the first time you switch to Map view, so the default List view stays lightweight. Tapping a pin auto-loads arrivals into its popup.
- 🌙 **Light/dark theme toggle**, persisted locally, defaulting to your OS preference
- Rate-limited via an API Gateway usage plan (see [Cost/Abuse Protection](#costabuse-protection)) since there's no user auth — this is meant for personal/low-traffic use

### Architecture

```
Browser (geolocation, favorites in localStorage)
   │  fetch() with x-api-key header
   ▼
API Gateway (usage plan: throttle + daily quota, API key required)
   │
   ▼
Lambda (lambda/app.py) ── proxies ──▶ LTA DataMall API (AccountKey stays server-side)
```

Routes:
| Route | Purpose |
|---|---|
| `GET /nearby?lat=&lon=&radius=` | Bus stops within `radius` km (default 0.5, capped 0.1–5) of a coordinate |
| `GET /arrival?busStopCode=` | Real-time arrivals for a stop |
| `GET /stop?code=` | Look up a stop's description/road name by code (used for favorites) |

The frontend is a static file — host it however you like (S3 + CloudFront, GitHub Pages, etc.). It is **not** included in the SAM stack; deploy it separately.

### Deploying the backend

Requires [AWS SAM CLI](https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/install-sam-cli.html) and Python 3.12 available locally (`brew install aws-sam-cli python@3.12` on macOS).

```bash
sam build
sam deploy --guided \
  --parameter-overrides LtaApiKey=<your LTA DataMall AccountKey> AllowedOrigin=<your frontend's origin, e.g. https://example.cloudfront.net>
```

### Deploying the frontend

`frontend/index.html` is committed with placeholders (`__API_URL__`, `__API_KEY__`) — **not** real values, so the file in git never contains a live credential. The real values are filled in only at upload time by `scripts/deploy-frontend.sh`, which reads them from the deployed stack and writes the filled-in copy to a gitignored `.build/` directory:

```bash
STACK_NAME=bus-stop-finder \
AWS_REGION=ap-southeast-1 \
S3_DEST=s3://<your-bucket>/<path>/index.html \
CLOUDFRONT_DISTRIBUTION_ID=<your distribution id>   # optional, invalidates the cache after upload
./scripts/deploy-frontend.sh
```

Swap the `S3_DEST` line for whatever static host you use if not S3+CloudFront — the templating step (`sed` on the two placeholders) works the same regardless of where the file ends up.

#### Tradeoff: this only keeps the key out of git, not off the internet

Templating at deploy time solves **"don't put the key in version control history"** — a real concern for a public repo, since git history is effectively permanent and searchable. It does **not** make the key secret at runtime: anyone who visits the live page can find it instantly via view-source, browser devtools' Network tab, or just downloading the HTML. That's inherent to any purely static frontend calling a key-gated API — the key has to ship to the browser somehow.

That's an acceptable tradeoff *only* because this key is deliberately not a bearer of real privilege — it's gated by the usage plan (rate/burst/daily quota in [Cost/Abuse Protection](#costabuse-protection)), so a leaked key costs you quota, not money or data. If that's not comfortable enough for your use case, the actual fixes are:

- **Rotate periodically**: re-deploy with a renamed `ApiKeyV2`-style resource in `template.yaml` (CloudFormation replaces it, deleting the old key) whenever you suspect exposure — this repo's key has already been rotated once this way.
- **Real auth**: put a Cognito User Pool (or any login) in front, and have API Gateway validate a per-user JWT instead of a shared static key — closes the "anyone can see it in devtools" gap entirely, at the cost of adding a login flow.
- **Keep the repo private**: if the frontend source doesn't need to be public, a private GitHub repo removes the "git history is public forever" half of the concern, though the *deployed page* is still whatever you choose to make public regardless of repo visibility.

### Cost/abuse protection

There's no user authentication — anyone with the URL can use the tool, so protection is capped blast radius rather than access control:

- **API Gateway usage plan**: 2 requests/sec, burst 3, **500 requests/day** total (shared across all callers, not per-user)
- **API key required** on every route — lets you rotate/revoke without redeploying Lambda
- **CORS** restricted to the `AllowedOrigin` you deploy with, so other websites' JS can't call your API using a leaked key (browsers only — doesn't stop direct API calls, e.g. via curl)

Worst case if the URL/key leak: the daily quota gets exhausted by someone else and you temporarily lose access to your own tool — not a runaway AWS bill. Adjust `template.yaml`'s `Throttle`/`Quota` values and redeploy if you want it tighter or looser.

---

## CLI Tool

A comprehensive command-line tool for finding bus stops and checking real-time bus arrivals in Singapore.

### Features

- **Real-Time Bus Arrivals**: Check arrival times for buses at any bus stop
- **Automatic Location Detection**: Uses IP geolocation or advanced GPS/WiFi triangulation
- **Smart Caching**: Caches bus stop data for 24 hours to reduce API calls
- **Flexible Search Options**: Search by bus stop code, coordinates, or current location
- **Error Handling**: API key validation and comprehensive error handling
- **Efficient Pagination**: Fetches all 5000+ bus stops from Singapore

## Prerequisites

- Python 3.8 or higher
- [uv](https://docs.astral.sh/uv/) - Fast Python package installer (recommended)
- LTA DataMall API key

## Installation

### 1. Install uv (if not already installed)

```bash
# macOS/Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# Or using Homebrew
brew install uv

# Or using pip
pip install uv
```

For other installation methods, see [uv installation guide](https://docs.astral.sh/uv/getting-started/installation/).

### 2. Clone or Download the Repository

```bash
git clone <repository-url>
cd lta_data_mall
```

### 3. Install Dependencies

```bash
# Install required dependencies using uv
uv pip install -r requirements.txt

# Optional: Install geocoder for advanced GPS detection
uv pip install geocoder
```

Alternatively, you can use uv's sync feature:

```bash
# Create a virtual environment and install dependencies
uv venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
uv pip install -r requirements.txt
```

### 4. Get an LTA DataMall API Key

1. Register at [LTA DataMall](https://datamall.lta.gov.sg/content/datamall/en/request-for-api.html)
2. Request an API key (AccountKey)
3. Wait for approval (usually within 1-2 business days)

### 5. Configure Environment Variables

```bash
# Copy the example file
cp .env.example .env

# Edit .env and add your API key
# Use your preferred text editor (nano, vim, code, etc.)
nano .env
```

Add your API key to the `.env` file:
```
LTA_API_KEY=your_actual_api_key_here
```

## Quick Start

After installation, try these commands:

```bash
# Check bus arrivals at a specific stop
python bus_stop_finder.py --bus-stop 13011

# Find bus stops near your current location
python bus_stop_finder.py

# Search for a bus stop by code
python bus_stop_finder.py --search-stop 13011

# Find all stops on a road
python bus_stop_finder.py --search-road "Orchard"
```

## Usage

### Check Bus Arrivals at a Specific Stop

Get real-time arrival times for all buses at a bus stop:

```bash
# Check arrivals at bus stop 13011
python bus_stop_finder.py --bus-stop 13011

# Or use the short form
python bus_stop_finder.py -b 13011
```

**Output:**
```
Bus Stop: 13011
Bus      Next Bus     Load               2nd Bus      3rd Bus     
Bus 14   2 min        🟢 Seats           8 min        15 min      
Bus 16   Arriving     🟡 Standing        12 min       N/A         
Bus 175  5 min        🔴 Limited         18 min       25 min      

Legend: 🟢 Seats Available | 🟡 Standing Available | 🔴 Limited Standing
```

### Find Nearby Bus Stops

#### Auto-detect Location (IP-based)

```bash
# Find stops within 500m of your current location
python bus_stop_finder.py

# Find stops within 1km radius
python bus_stop_finder.py --radius 1.0
```

#### Use Advanced GPS Detection

For better location accuracy using WiFi/cell tower triangulation:

```bash
# First install geocoder
uv pip install geocoder

# Then use the --gps flag
python bus_stop_finder.py --gps

# Combine with custom radius
python bus_stop_finder.py --gps --radius 1.0
```

#### Use Specific Coordinates

```bash
# Marina Bay Sands area
python bus_stop_finder.py --lat 1.2834 --lon 103.8607

# With custom radius
python bus_stop_finder.py --lat 1.2834 --lon 103.8607 --radius 0.3
```

#### Force Fresh Data

```bash
# Bypass cache and fetch fresh data from API
python bus_stop_finder.py --no-cache
```

### Search for Bus Stops

#### Search by Bus Stop Code

```bash
# Get detailed information about a specific bus stop
python bus_stop_finder.py --search-stop 13011
```

#### Search by Road Name

```bash
# Find all bus stops on a road (case-insensitive partial match)
python bus_stop_finder.py --search-road "Orchard"
python bus_stop_finder.py --search-road "Toa Payoh"
```

### Command Line Options

```
usage: bus_stop_finder.py [-h] [--bus-stop BUS_STOP] [--search-stop SEARCH_STOP]
                          [--search-road SEARCH_ROAD] [--lat LAT] [--lon LON]
                          [--radius RADIUS] [--no-cache] [--gps]

Find nearby bus stops in Singapore

optional arguments:
  -h, --help            show this help message and exit
  --bus-stop BUS_STOP, -b BUS_STOP
                        Bus stop code to check arrivals (e.g., 13011)
  --search-stop SEARCH_STOP, -s SEARCH_STOP
                        Search for bus stop details by code (e.g., 13011)
  --search-road SEARCH_ROAD, -r SEARCH_ROAD
                        Search for bus stops by road name (e.g., "Orchard Road")
  --lat LAT             Latitude of the location
  --lon LON             Longitude of the location
  --radius RADIUS       Search radius in kilometers (default: 0.5)
  --no-cache            Force fetch fresh data from API instead of using cache
  --gps                 Use advanced GPS/WiFi triangulation for better location
                        accuracy (requires geocoder library)

Examples:
  bus_stop_finder.py                           # Use current location (IP-based)
  bus_stop_finder.py --bus-stop 13011          # Check arrivals at stop 13011
  bus_stop_finder.py --search-stop 13011       # Show details for stop 13011
  bus_stop_finder.py --search-road "Orchard"   # Find all stops on Orchard Road
  bus_stop_finder.py --lat 1.2834 --lon 103.8607  # Use specific coordinates
  bus_stop_finder.py --radius 1.0              # Search within 1km radius
  bus_stop_finder.py --no-cache                # Force fresh data from API
  bus_stop_finder.py --gps                     # Use advanced GPS detection
```

### Programmatic Usage

```python
from bus_stop_finder import (
    find_nearby_bus_stops, 
    display_bus_stops, 
    get_current_location,
    get_gps_location,
    get_bus_stop_by_code,
    get_bus_arrival,
    search_bus_stops_by_road
)

# Option 1: Check bus arrivals at a specific stop
arrival_data = get_bus_arrival("13011")
print(arrival_data)

# Option 2: Search for bus stop details
bus_stop = get_bus_stop_by_code("13011")
if bus_stop:
    print(f"{bus_stop['Description']} on {bus_stop['RoadName']}")

# Option 3: Search by road name
stops = search_bus_stops_by_road("Orchard")
for stop in stops:
    print(f"{stop['BusStopCode']}: {stop['Description']}")

# Option 4: Use auto-detected location (IP-based)
location = get_current_location()
if location:
    latitude, longitude = location
    nearby = find_nearby_bus_stops(latitude, longitude, radius_km=0.5)
    display_bus_stops(nearby)

# Option 5: Use advanced GPS detection
location = get_gps_location()
if location:
    latitude, longitude = location
    nearby = find_nearby_bus_stops(latitude, longitude, radius_km=0.5)

# Option 6: Use specific coordinates
latitude = 1.3521
longitude = 103.8198
nearby = find_nearby_bus_stops(latitude, longitude, radius_km=0.5)

# Option 7: Force refresh cache (bypass 24-hour cache)
nearby = find_nearby_bus_stops(latitude, longitude, radius_km=0.5, use_cache=False)

# Process the data yourself
for stop in nearby:
    print(f"{stop['BusStopCode']}: {stop['RoadName']} - {stop['Distance']}m away")
```

### Caching Behavior

- **First run**: Fetches all ~5000 bus stops from API and saves to `data/bus_stops_cache.json`
- **Subsequent runs**: Uses cached data if less than 24 hours old
- **Cache expiry**: Automatically refreshes cache after 24 hours
- **Manual refresh**: Pass `use_cache=False` to force fresh data

## Location Detection

The script supports multiple location detection methods:

### IP-Based Geolocation (Default)
- **Accuracy**: Approximate, typically accurate to city level
- **Limitations**: May not work correctly behind VPNs or corporate networks
- **Privacy**: Makes a request to `http://ip-api.com/json/` to determine location
- **Fallback**: If detection fails, defaults to Marina Bay Sands coordinates

### Advanced GPS Detection (Optional)
- **Accuracy**: More precise using WiFi/cell tower triangulation
- **Requirements**: Install `geocoder` library (`uv pip install geocoder`)
- **Usage**: Add `--gps` flag
- **Providers**: Uses multiple providers (IP services, Google geolocation, OpenStreetMap)
- **Fallback**: If GPS fails, falls back to IP-based geolocation

For production mobile apps, consider using device GPS instead of these methods.

## Output Formats

### Bus Arrival Display

When checking a specific bus stop (`--bus-stop`):
- Bus service number
- Next bus arrival time (in minutes or "Arriving")
- Load status with visual indicators:
  - 🟢 Seats Available
  - 🟡 Standing Available
  - 🔴 Limited Standing
- Second and third bus arrival times

### Nearby Bus Stops Display

When searching for nearby stops:
- Bus Stop Code (5-digit identifier)
- Road Name
- Description (landmarks near the bus stop)
- Distance in meters (sorted from nearest to farthest)

## Example Outputs

### Bus Arrivals Example

```
2026-01-17 16:30:45 - INFO - Fetching bus arrivals for bus stop: 13011

==========================================================================================
Bus Stop: 13011
==========================================================================================
Bus      Next Bus     Load               2nd Bus      3rd Bus     
------------------------------------------------------------------------------------------
14       2 min        🟢 Seats           8 min        15 min      
16       Arriving     🟡 Standing        12 min       N/A         
36       4 min        🟢 Seats           14 min       24 min      
175      5 min        🔴 Limited         18 min       25 min      
==========================================================================================

Total: 4 bus services
Legend: 🟢 Seats Available | 🟡 Standing Available | 🔴 Limited Standing
```

### Nearby Bus Stops Example

```
2026-01-17 16:30:45 - INFO - Attempting to detect your location...
2026-01-17 16:30:46 - INFO - Location detected: Singapore, Singapore (1.3521, 103.8198)
2026-01-17 16:30:46 - INFO - Using cached bus stops (cached at 2026-01-17 10:15:30)
2026-01-17 16:30:46 - INFO - Searching for bus stops within 0.5km of (1.3521, 103.8198)...
2026-01-17 16:30:46 - INFO - Found 12 bus stops within 0.5km

================================================================================
Code     Road Name                 Description                    Distance (m)
================================================================================
03211    Raffles Blvd             Marina Bay Sands               127         
03212    Raffles Ave              Opp The Ritz-Carlton           243         
03219    Temasek Blvd             Millenia Twr                   318         
================================================================================

Total: 12 bus stops found
```

## Files Generated

- `data/bus_stops_cache.json`: Cached bus stop data (auto-generated)
- Contains timestamp and all bus stop information
- Automatically refreshed every 24 hours
- The `data/` directory is created automatically if it doesn't exist

## API Rate Limits

- LTA DataMall API returns 500 records per call
- Script handles pagination automatically
- Caching reduces API calls significantly
- First run makes ~10-12 API calls to fetch all stops
- Subsequent runs use cache (0 API calls within 24 hours)
- Bus arrival queries make 1 API call per request (not cached)

## Notes

- The API requires an AccountKey (lowercase 'a') in the header for authentication
- Bus stop data is relatively static, so 24-hour caching is reasonable
- Bus arrival data is real-time and not cached
- The Haversine formula provides accurate distance calculations for nearby locations
- Load indicators help you decide which bus to board based on available space

## Troubleshooting

### API Key Issues

If you get authentication errors:
1. Verify your API key is correct in `.env`
2. Check that the key is active on the LTA DataMall portal
3. Ensure there are no extra spaces or quotes around the key

### Location Detection Issues

If location detection fails:
- Try using `--gps` flag for better accuracy
- Manually specify coordinates with `--lat` and `--lon`
- Check your internet connection
- VPNs may affect IP-based location detection

### Cache Issues

If you're seeing stale data:
- Use `--no-cache` flag to force fresh data
- Delete `data/bus_stops_cache.json` manually
- Check file permissions on the `data/` directory

### Import Errors

If you get module import errors:
```bash
# Ensure you're in the correct directory
cd lta_data_mall

# Reinstall dependencies
uv pip install -r requirements.txt

# If using a virtual environment, ensure it's activated
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
```

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

This project is licensed under the MIT License.

## Acknowledgments

- Data provided by [LTA DataMall](https://datamall.lta.gov.sg/)
- Built with Python and the LTA DataMall API
