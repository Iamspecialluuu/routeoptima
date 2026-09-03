# TSP Dispatch Route Optimization System

Project: Optimization of Delivery Routes for Dispatch Riders Using the Traveling Salesman Problem (TSP) Algorithm.

## Features
- Administrator login/session
- Dashboard statistics
- Rider management
- Delivery management and status
- Exact TSP for up to 10 selected stops
- Nearest Neighbour heuristic for larger datasets
- Haversine geographic distance
- Before/after route-distance comparison
- Percentage improvement and execution time
- SQLite persistence and route history
- Google Maps visualization
- Backend/architecture explanation page

## Run
python -m venv venv
# Windows: venv\\Scripts\\activate
# Android/Termux: source venv/bin/activate
pip install -r requirements.txt
python app.py
Open http://127.0.0.1:5000

Demo login: admin / admin123

## Google Maps
Set GOOGLE_MAPS_API_KEY to your restricted Google Maps JavaScript API key before starting the app. Do not publish your real key in source control.

## Defense testing
Use 5-10 locations for Exact TSP. Record initial distance, optimized distance, distance saved, improvement percentage, and execution time. For larger datasets use Nearest Neighbour.
