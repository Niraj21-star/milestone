import sys
import json
import requests

def test_api():
    url = "http://localhost:8000/api/plan-trip/"
    payload = {
        "current_location": "Chicago, IL",
        "pickup_location": "Indianapolis, IN",
        "dropoff_location": "Denver, CO",
        "current_cycle_used_hours": 10.0
    }
    
    print(f"Sending POST request to {url}")
    print(f"Payload: {json.dumps(payload, indent=2)}")
    
    try:
        response = requests.post(url, json=payload, timeout=30)
        print(f"\nResponse Status: {response.status_code}")
        
        data = response.json()
        print("\n--- Summary ---")
        print(json.dumps(data.get("summary", {}), indent=2))
        
        print("\n--- Daily Logs Overview ---")
        logs = data.get("daily_logs", [])
        print(f"Total days: {len(logs)}")
        for log in logs:
            print(f"Day {log['day_index']} ({log['date']}): {log['totals_minutes']}")
            
        print("\n--- Events ---")
        print(f"Total canonical events: {len(data.get('events', []))}")
        
    except requests.exceptions.ConnectionError:
        print("\nError: Could not connect to the Django server. Is it running on port 8000?")
    except Exception as e:
        print(f"\nError: {e}")

if __name__ == "__main__":
    test_api()
