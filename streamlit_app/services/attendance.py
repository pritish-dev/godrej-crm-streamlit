import requests
import pandas as pd

API_URL = "https://onlinerealsoft.com/api/attendance-log"  # replace this

def fetch_attendance(from_date=None, to_date=None):
    try:
        params = {}

        if from_date:
            params["from_date"] = from_date
        if to_date:
            params["to_date"] = to_date

        res = requests.get(API_URL, params=params)

        if res.status_code != 200:
            raise Exception(f"API error {res.status_code}")

        data = res.json()

        df = pd.DataFrame(data)

        # normalize columns
        df.rename(columns={
            "emp_code": "Employee ID",
            "emp_name": "Employee Name",
            "direction": "Direction",
            "log_datetime": "Log Time",
            "device": "Device"
        }, inplace=True)

        return df

    except Exception as e:
        print("Error:", e)
        return pd.DataFrame()