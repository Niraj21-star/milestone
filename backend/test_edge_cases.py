import requests
import json
import time

API_URL = "http://127.0.0.1:8000/api/plan-trip/"

def test_case(name, payload):
    print(f"\n--- Testing: {name} ---")
    try:
        start = time.time()
        resp = requests.post(API_URL, json=payload)
        dur = time.time() - start
        
        if resp.status_code == 200:
            data = resp.json()
            summary = data.get("summary", {})
            compliance = data.get("compliance", {})
            logs = data.get("daily_logs", [])
            print(f"Success ({dur:.2f}s): {summary.get('total_miles')} mi, {summary.get('driving_hours')} hrs driving")
            print(f"Compliant: {compliance.get('is_compliant', False)}")
            print(f"Days: {len(logs)}")
            
            # Check 1440 mins
            for log in logs:
                totals = log.get("totals_minutes", {})
                total_mins = sum(totals.values())
                if total_mins != 1440:
                    print(f"WARNING: Day {log.get('date')} has {total_mins} mins instead of 1440!")
                
        else:
            print(f"Error ({resp.status_code}): {resp.text}")
    except Exception as e:
        print(f"Failed to connect: {e}")

if __name__ == "__main__":
    test_case("A. Short trip", {
        "current_location": "Chicago, IL",
        "pickup_location": "Gary, IN",
        "dropoff_location": "Indianapolis, IN",
        "current_cycle_used": 0.0
    })

    test_case("B. Multi-day trip", {
        "current_location": "Seattle, WA",
        "pickup_location": "Portland, OR",
        "dropoff_location": "Miami, FL",
        "current_cycle_used": 0.0
    })
    
    test_case("E. Multiple fuel stops", {
        "current_location": "Los Angeles, CA",
        "pickup_location": "Phoenix, AZ",
        "dropoff_location": "New York, NY",
        "current_cycle_used": 0.0
    })

    test_case("G. Current cycle = 69.9", {
        "current_location": "Chicago, IL",
        "pickup_location": "Gary, IN",
        "dropoff_location": "Indianapolis, IN",
        "current_cycle_used": 69.9
    })

    test_case("H. Current cycle = 70", {
        "current_location": "Chicago, IL",
        "pickup_location": "Gary, IN",
        "dropoff_location": "Indianapolis, IN",
        "current_cycle_used": 70
    })

    test_case("I. Routing failure / J. Geocoding failure", {
        "current_location": "FAKE_CITY_XYZ_12345",
        "pickup_location": "Chicago, IL",
        "dropoff_location": "Indianapolis, IN",
        "current_cycle_used": 0.0
    })

    test_case("N. Empty/invalid location", {
        "current_location": "",
        "pickup_location": "Chicago, IL",
        "dropoff_location": "Indianapolis, IN",
        "current_cycle_used": 0.0
    })
