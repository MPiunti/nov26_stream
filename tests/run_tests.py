# Databricks notebook source
# MAGIC %md
# MAGIC # Run the project's tests
# MAGIC Runs every test in this folder on Databricks, from the Git folder, and fails if any test fails.
# MAGIC
# MAGIC Run it before deploying, after pulling a change. The tests read only the project's files; they don't touch any table or pipeline.
# MAGIC See "Tests" in `readme.md`.

# COMMAND ----------

import os
import sys
import unittest

tests_folder = os.getcwd()  # a notebook's working directory is its own folder
sys.path.insert(0, tests_folder)
sys.dont_write_bytecode = True

suite = unittest.defaultTestLoader.discover(tests_folder, pattern="test_*.py")
result = unittest.TextTestRunner(verbosity=2).run(suite)
print(f"Ran {result.testsRun} tests: {len(result.failures)} failed, {len(result.errors)} errors, "
      f"{len(result.skipped)} skipped")
if not result.wasSuccessful():
    raise RuntimeError("Some tests failed. Don't deploy until they pass.")
