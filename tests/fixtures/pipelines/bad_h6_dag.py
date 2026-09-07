"""Fails only H6: the ``transform >> load`` edge is missing."""

from datetime import datetime

from airflow import DAG
from airflow.operators.python import PythonOperator

import pipeline

with DAG(
    dag_id="acme__ledger",
    schedule="0 6 * * 1-5",
    start_date=datetime(2025, 1, 1),
    catchup=False,
) as dag:
    extract = PythonOperator(task_id="extract", python_callable=pipeline.extract)
    transform = PythonOperator(task_id="transform", python_callable=pipeline.transform)
    load = PythonOperator(task_id="load", python_callable=pipeline.load)

    extract >> transform
