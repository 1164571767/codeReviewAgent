"""Deliberately flawed module used to demo the reviewer agent."""

import json  # noqa: F401  (unused on purpose)
import os


def load_config(path, cache={}):  # mutable default argument
    if path in cache:
        return cache[path]
    f = open(path)
    data = json.load(f)
    cache[path] = data
    return data


def divide(a, b):
    try:
        return a / b
    except:  # bare except
        return 0


def run(cmd):
    os.system("echo " + cmd)  # shell injection risk


def find_user(conn, name):
    cursor = conn.cursor()
    query = "SELECT * FROM users WHERE name = '%s'" % name  # SQL injection risk
    cursor.execute(query)
    return cursor.fetchone()


def total(values):
    result = 0
    for i in range(len(values)):
        result = result + values[i]
    return result
