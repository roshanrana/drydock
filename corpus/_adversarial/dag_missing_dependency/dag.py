"""Almost-right DAG: the load task is declared but never wired after transform."""

from datetime import datetime

import pipeline
from airflow import DAG
from airflow.operators.python import PythonOperator

with DAG(
    dag_id="acme-treasury__daily_cash",
    schedule="0 6 * * 1-5",
    start_date=datetime(2026, 9, 1),
    catchup=False,
) as dag:
    extract = PythonOperator(
        task_id="extract",
        python_callable=pipeline.extract,
        op_args=["/data/inbound/acme-treasury/daily_cash.csv"],
    )
    transform = PythonOperator(task_id="transform", python_callable=pipeline.transform)
    load = PythonOperator(task_id="load", python_callable=pipeline.load)

    extract >> transform  # load is declared above but never wired downstream
