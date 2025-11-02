from datetime import timedelta
import json
import os
import threading
from async_test import get_all

from flask import Flask, Response, request, render_template
import redis

from controllers.all_results_service import AllResults
from controllers.service import Service
from controllers.async_service import get_results_async
from utils.utils import calculate_sgpa, get_hallticket_helper

# redis_client = redis.Redis(host="localhost", port=6379, db=0)
redis_url = os.environ.get("REDISURL")
if redis_url:
    redis_client = redis.from_url(redis_url, decode_responses=True)
else:
    # Fallback for local development
    redis_client = redis.Redis(
        host="localhost", port=6379, db=0, decode_responses=True)

# Helper functions for safe Redis operations


def safe_redis_get(key):
    """Safely get value from Redis, return None on error"""
    try:
        return redis_client.get(key)
    except Exception as e:
        print(f"Redis GET error: {e}")
        return None


def safe_redis_set(key, value, expire_seconds=None):
    """Safely set value in Redis, silently fail on error"""
    try:
        redis_client.set(key, value)
        if expire_seconds:
            redis_client.expire(key, timedelta(seconds=expire_seconds))
        return True
    except Exception as e:
        print(f"Redis SET error: {e}")
        return False


# Initializing the Crawler object from service
# Injecting the driver dependency
old_scrapper = Service()
new_scrapper = AllResults()


app = Flask(__name__)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/all-r18/<hallticket>")
def fetch_all_r18_results(hallticket):
    current_key = f"r18-{hallticket.lower()}"

    redis_response = safe_redis_get(current_key)
    if redis_response is not None:
        data = json.loads(redis_response)
        return Response(json.dumps(data), mimetype="application/json")
    results = {}
    all_results = []
    try:
        async_results = get_all(hallticket)
        for result in async_results:
            # checking if the dictionary has empty value
            if not list(result.values())[0]:
                print(result)
                continue
            if not results:
                results["details"] = result["student_details"]
            new = {
                key: value
                for key, value in result.items()
                if key != "student_details" and value
            }
            if new:
                all_results.append(new)
    except Exception as e:
        print("EXCEPTION", e)
        return Response(
            json.dumps({"error": "something went wrong with server" + str(e)}),
            mimetype="application/json",
        )
    results["results"] = all_results
    total_gpa = 0
    for year in results["results"]:
        if len(year) < 2:
            total_gpa = 0
            break
        total_gpa += float(year["SGPA"])
    if total_gpa:
        total_gpa /= len(results["results"])
        results["overall_gpa"] = round(total_gpa, 2)

    # Cache only if results exist
    if results["results"]:
        safe_redis_set(current_key, json.dumps(
            {"data": results}), expire_seconds=3*60*60)
    return Response(json.dumps({"data": results}), mimetype="application/json")


@app.route("/<hallticket>/<dob>/<year>", methods=["GET"])
def routing_path(hallticket, dob, year):
    current_key = f"{hallticket}-{year}"

    redis_response = safe_redis_get(current_key)
    if redis_response is not None:
        result = json.loads(redis_response)
    else:
        result = old_scrapper.get_result(hallticket, dob, year)
        if "error" in result:
            return Response(json.dumps(result), mimetype="application/json", status=503)
        safe_redis_set(current_key, json.dumps(result), expire_seconds=30*60)

    return Response(json.dumps(result), mimetype="application/json")


@app.route("/calculate/<hallticket>/<dob>/<year>", methods=["GET"])
def calculate(hallticket, dob, year):
    current_key = f"calculate-{hallticket}-{year}"

    redis_response = safe_redis_get(current_key)
    if redis_response is not None:
        result = json.loads(redis_response)
    else:
        result = old_scrapper.get_result(hallticket, dob, year)
        if "error" in result:
            return Response(json.dumps(result), mimetype="application/json", status=503)
        result = calculate_sgpa(result)
        safe_redis_set(current_key, json.dumps(result), expire_seconds=30*60)

    return Response(json.dumps(result), mimetype="application/json")


@app.route("/result", methods=["GET"])
def request_param_path():

    hallticket = request.args.get("hallticket")
    dob = request.args.get("dob")
    year = request.args.get("year")

    current_key = f"result-{hallticket}-{year}"
    redis_response = safe_redis_get(current_key)
    if redis_response is not None:
        result = json.loads(redis_response)
    else:
        result = old_scrapper.get_result(hallticket, dob, year)
        if "error" in result:
            return Response(json.dumps(result), mimetype="application/json", status=503)
        safe_redis_set(current_key, json.dumps(result), expire_seconds=30*60)

    return Response(json.dumps(result), mimetype="application/json")


@app.route("/new/all", methods=["GET"])
def all_results():
    current_key = "all_exams"

    redis_response = safe_redis_get(current_key)
    if redis_response is not None:
        all_exams = json.loads(redis_response)
    else:
        all_exams, _, _, _ = new_scrapper.get_all_results()
        safe_redis_set(current_key, json.dumps(
            all_exams), expire_seconds=30*60)

    return Response(json.dumps(all_exams), mimetype="application/json")


@app.route("/new/all/regular", methods=["GET"])
def all_regular():
    current_key = "all_regular"
    refresh = request.args.get("refresh")
    if refresh is not None:
        refresh = True

    redis_response = safe_redis_get(current_key)
    if redis_response is not None and not refresh:
        regular_exams = json.loads(redis_response)
    else:
        _, regular_exams, _, _ = new_scrapper.get_all_results()
        if regular_exams:
            safe_redis_set(current_key, json.dumps(
                regular_exams), expire_seconds=30*60)

    return Response(json.dumps(regular_exams), mimetype="application/json")


@app.route("/new/all/supply", methods=["GET"])
def all_supply():
    current_key = "all_supply"
    refresh = request.args.get("refresh")
    if refresh is not None:
        refresh = True
    redis_response = safe_redis_get(current_key)
    if redis_response is not None and not refresh:
        supply_exams = json.loads(redis_response)
    else:
        _, _, supply_exams, _ = new_scrapper.get_all_results()
        if supply_exams:
            safe_redis_set(current_key, json.dumps(
                supply_exams), expire_seconds=30*60)

    return Response(json.dumps(supply_exams), mimetype="application/json")


@app.route("/api", methods=["GET"])
def get_specific_result():
    hallticket = request.args.get("hallticket")
    dob = request.args.get("dob")
    degree = request.args.get("degree")
    examCode = request.args.get("examCode")
    etype = request.args.get("etype")
    type = request.args.get("type")
    result = request.args.get("result") or ""
    print(hallticket, dob, degree, examCode, etype, type, result)

    current_key = f"{hallticket}-{degree}-{examCode}-{etype}-{type}-{result}"

    redis_response = safe_redis_get(current_key)
    if redis_response is not None:
        resp = json.loads(redis_response)
    else:
        resp = old_scrapper.get_result_with_url(
            hallticket, dob, degree, examCode, etype, type, result
        )
        if "error" in resp:
            return Response(json.dumps(resp), mimetype="application/json", status=503)
        safe_redis_set(current_key, json.dumps(resp), expire_seconds=30*60)

    return Response(json.dumps(resp), mimetype="application/json")


@app.route("/api/calculate", methods=["GET"])
def get_specific_result_with_sgpa():
    hallticket = request.args.get("hallticket")
    dob = request.args.get("dob")
    degree = request.args.get("degree")
    examCode = request.args.get("examCode")
    etype = request.args.get("etype")
    type = request.args.get("type")
    result = request.args.get("result") or ""

    current_key = f"calculate-{hallticket}-{
        degree}-{examCode}-{etype}-{type}-{result}"
    redis_response = safe_redis_get(current_key)
    if redis_response is not None:
        result = json.loads(redis_response)
    else:
        resp = old_scrapper.get_result_with_url(
            hallticket, dob, degree, examCode, etype, type, result
        )
        if "error" in resp:
            return Response(json.dumps(resp), mimetype="application/json", status=503)
        result = calculate_sgpa(resp)
        safe_redis_set(current_key, json.dumps(result), expire_seconds=30*60)

    return Response(json.dumps(result), mimetype="application/json")


@app.route("/api/bulk/calculate", methods=["GET"])
def get_bulk_results():

    from utils.constants import string_dict

    hallticket_from = request.args.get("hallticket_from").upper()
    hallticket_to = request.args.get("hallticket_to").upper()
    degree = request.args.get("degree")
    examCode = request.args.get("examCode")
    etype = request.args.get("etype")
    type = request.args.get("type")
    result = request.args.get("result") or "null"
    # hallticket = hallticket_from[:-2]

    if hallticket_from[0:8] != hallticket_to[0:8]:
        return Exception("Starting and ending hallticket should be same")

    roll_number = hallticket_from[0:8]
    s1 = str(hallticket_from[8:10])
    s2 = str(hallticket_to[8:10])

    def test(s1):
        try:
            s1 = int(s1)
            return s1
        except:
            s1 = str(string_dict[s1[0]]) + str(s1[1])
            s1 = 100 + int(s1)
        return s1

    start = test(s1)
    end = test(s2)

    if end - start < 0 or end - start > 210:
        return Exception("SOMETHING WENT WRONG")

    redis_response = safe_redis_get(
        hallticket_from + hallticket_to + examCode + etype + type
    )
    if redis_response is not None:
        return Response(redis_response, mimetype="application/json")

    # Check if all the halltickets are already cached, if so, return them.
    results = []
    for i in range(start, end + 1):

        hallticket = get_hallticket_helper(roll_number, i)
        current_key = (
            f"calculate-{hallticket}-{degree}-{examCode}-{etype}-{type}-{result}"
        )
        redis_response = safe_redis_get(current_key)

        if redis_response is not None:
            redis_out = json.loads(redis_response)
            results.append(redis_out)
        else:
            break
    else:
        print("DIDN'T CREATE A NEW KEY, GOT RESULTS FROM HALLTICKETS CACHED")
        return Response(json.dumps(results), mimetype="application/json")

    safe_redis_set(
        hallticket_from + hallticket_to + examCode + etype + type,
        json.dumps({"result": "loading"}),
        expire_seconds=10*60
    )

    def worker(hallticket_from, hallticket_to):
        print("WORKER IS RUNNING")
        results = get_results_async(
            hallticket_from, hallticket_to, examCode, etype, type, result, redis_client
        )

        safe_redis_set(
            hallticket_from + hallticket_to + examCode + etype + type,
            json.dumps(results),
            expire_seconds=10*60
        )

    threading.Thread(target=worker, args=(
        hallticket_from, hallticket_to)).start()

    # This is only going to return in the first call.
    return Response(
        safe_redis_get(hallticket_from + hallticket_to +
                       examCode + etype + type),
        mimetype="application/json",
    )


@app.route("/new/", methods=["GET"])
def all_unordered_results():
    _, _, _, unordered_results = new_scrapper.get_all_results()
    return Response(json.dumps(unordered_results), mimetype="application/json")


@app.route("/notifications", methods=["GET"])
def notifications():
    refresh = request.args.get("refresh")
    if refresh is not None:
        refresh = True
    current_key = "notifications"

    # redis_response = safe_redis_get(current_key)
    # if redis_response is not None and not refresh:
    #     result = json.loads(redis_response)
    # else:
    result = new_scrapper.get_notifiations()
    safe_redis_set(current_key, json.dumps(result), expire_seconds=30*60)

    return Response(json.dumps(result), mimetype="application/json")


if __name__ == "__main__":

    app.run()
