from flask import Blueprint, Response
from datetime import timedelta
import json
import redis
from selenium import webdriver

from controllers.all_results_service import AllResults
import platform
from controllers.service import Service
import os
# from controllers.async_service import get_results_async
# from utils.utils import calculate_sgpa, get_hallticket_helper


r18_view = Blueprint('r18_view', __name__)

def init_firefox_driver():
    firefox_options = webdriver.FirefoxOptions()
    driver_file = (
        "drivers/geckodriver"
        if platform.system() == "Linux"
        else "drivers/geckodriver.exe"
    )
    # Arguments for Firefox driver
    firefox_options.add_argument("--headless")
    firefox_options.add_argument("--no-sandbox")
    firefox_options.add_argument("--disable-dev-shm-usage")

    # Firefox Driver
    driver = webdriver.Firefox(
        executable_path=os.path.join(os.getcwd(), driver_file), options=firefox_options
    )

    return driver

driver = init_firefox_driver()
print(driver)
redis_client = redis.Redis(host="localhost", port=6379, db=0)
# driver = init_chrome_driver()
# redis_client = redis.from_url(os.environ.get("REDIS_URL"))

old_scrapper = Service(driver)
new_scrapper = AllResults(driver)

@r18_view.route("/<hallticket>/<dob>/<year>", methods=["GET"])
def routing_path(hallticket, dob, year):
    current_key = f"{hallticket}-{year}"

    redis_response = redis_client.get(current_key)
    if redis_response != None:
        result = json.loads(redis_response)
    else:
        result = old_scrapper.get_result(hallticket, dob, year)
        if "error" in result:
            return Response(json.dumps(result), mimetype="application/json", status=503)
        redis_client.set(current_key, json.dumps(result))
        redis_client.expire(current_key, timedelta(minutes=30))

    return Response(json.dumps(result), mimetype="application/json")
