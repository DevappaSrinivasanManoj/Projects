import requests
import csv
from datetime import datetime

# Open-Meteo API endpoint
latitude = "12.9411"  # Replace with your latitude
longitude = "77.49206"  # Replace with your longitude
url = f"https://api.open-meteo.com/v1/forecast?latitude={latitude}&longitude={longitude}&hourly=temperature_2m,relativehumidity_2m,cloudcover,windspeed_10m,precipitation&timezone=auto"

# Fetch data from Open-Meteo
response = requests.get(url).json()
hourly_data = response["hourly"]

# Get today's date in YYYY-MM-DD format
today = datetime.today().strftime("%Y-%m-%d")

# Filter hourly data for today
today_hours = [i for i, time in enumerate(hourly_data["time"]) if time.startswith(today)]

# Extract today's hourly data
hourly_temps = [hourly_data["temperature_2m"][i] for i in today_hours]
hourly_humidity = [hourly_data["relativehumidity_2m"][i] for i in today_hours]
hourly_cloudcover = [hourly_data["cloudcover"][i] for i in today_hours]
hourly_windspeed = [hourly_data["windspeed_10m"][i] for i in today_hours]
hourly_precipitation = [hourly_data["precipitation"][i] for i in today_hours]

# Calculate daily averages
avg_temperature = sum(hourly_temps) / len(hourly_temps)
avg_humidity = sum(hourly_humidity) / len(hourly_humidity)
avg_cloudcover = sum(hourly_cloudcover) / len(hourly_cloudcover)
avg_windspeed = sum(hourly_windspeed) / len(hourly_windspeed)
total_precipitation = sum(hourly_precipitation)

# Append daily averages to CSV
with open("daily_solar_data.csv", "a", newline="") as file:
    writer = csv.writer(file)
    # Write daily data (no header)
    writer.writerow([today, avg_temperature, avg_humidity, avg_cloudcover, avg_windspeed, total_precipitation, ""])  # Leave "Is it Heated" blank for manual input

print("Today's data appended successfully!")
