#!/usr/bin/env python

import subprocess
import time
from pathlib import Path

import schedule

HERE = Path(__file__).parent


def hourly():
    print("Running hourly job...")
    script = HERE.joinpath("scheduler-hourly")
    subprocess.check_call([str(script)], cwd=HERE.parent)


def daily():
    print("Running daily job...")
    script = HERE.joinpath("scheduler-daily")
    subprocess.check_call([str(script)], cwd=HERE.parent)


schedule.every().hour.do(hourly)
schedule.every().day.at("10:30").do(daily)

while True:
    schedule.run_pending()
    time.sleep(1)
