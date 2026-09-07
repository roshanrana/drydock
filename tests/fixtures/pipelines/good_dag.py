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
    extract = PythonOperator(
        task_id="extract",
        python_callable=pipeline.extract,
        op_args=["/data/acme/ledger.csv"],
    )
    transform = PythonOperator(task_id="transform", python_callable=pipeline.transform)
    load = PythonOperator(task_id="load", python_callable=pipeline.load)

    extract >> transform >> load
