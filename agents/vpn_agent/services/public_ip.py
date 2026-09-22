"""
public_ip.py — Fetches the current public IP address and optional geo details.
Uses ipify for the raw IP and ipapi.co for country/ISP detail.
"""

import requests

# Primary endpoint: fast, returns JSON with just the IP
IP_SIMPLE_URL = "https://api.ipify.org?format=json"

# Detail endpoint: returns country, city, ISP, org
IP_DETAIL_URL = "https://ipapi.co/json/"

# Timeout in seconds for all HTTP requests.
# Kept short so threads finish quickly when the app closes.
REQUEST_TIMEOUT = 4


def get_public_ip() -> str:
    """Return the current public IP as a string, or an error message."""
    try:
        response = requests.get(IP_SIMPLE_URL, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        data = response.json()
        return data.get("ip", "Unknown")
    except requests.exceptions.ConnectionError:
        return "No connection"
    except requests.exceptions.Timeout:
        return "Timeout"
    except Exception as e:
        return f"Error: {e}"


def get_ip_details() -> dict:
    """
    Return a dict with keys: ip, country, city, org, timezone.
    Returns partial data if the API is slow or partially fails.
    """
    result = {
        "ip": "Unknown",
        "country": "Unknown",
        "city": "Unknown",
        "org": "Unknown",
        "timezone": "Unknown",
    }
    try:
        response = requests.get(IP_DETAIL_URL, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        data = response.json()
        result["ip"] = data.get("ip", "Unknown")
        result["country"] = data.get("country_name", "Unknown")
        result["city"] = data.get("city", "Unknown")
        result["org"] = data.get("org", "Unknown")
        result["timezone"] = data.get("timezone", "Unknown")
    except Exception as e:
        result["ip"] = f"Error: {e}"
    return result
